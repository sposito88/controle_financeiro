"""
Bot de Controle Financeiro via Telegram
----------------------------------------
Envie uma foto, áudio ou texto → GPT-4o / Whisper extraem os dados → salva no Google Sheets

Dependências: pip install -r requirements.txt
"""

import csv
import io
import os
import json
import base64
import logging
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, time as dt_time, timezone

import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)
from openai import OpenAI
import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# ── Configuração ──────────────────────────────────────────────────────────
load_dotenv()

TELEGRAM_TOKEN       = os.environ["TELEGRAM_TOKEN"]
OPENAI_API_KEY       = os.environ["OPENAI_API_KEY"]
GOOGLE_SHEETS_ID     = os.environ["GOOGLE_SHEETS_ID"]
GOOGLE_CLIENT_ID     = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
GOOGLE_REFRESH_TOKEN = os.environ["GOOGLE_REFRESH_TOKEN"]
ALLOWED_USER_IDS     = [int(x) for x in os.environ.get("ALLOWED_USER_IDS", "").split(",") if x.strip()]
NOTIFY_USER_IDS      = [int(x) for x in os.environ.get("NOTIFY_USER_IDS",  "").split(",") if x.strip()]

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

openai_client = OpenAI(api_key=OPENAI_API_KEY)

BRT = timezone(timedelta(hours=-3))

CATEGORIAS = [
    "Alimentação", "Transporte", "Saúde", "Educação",
    "Lazer", "Moradia", "Vestuário", "Receita", "Outros",
]


def _norm(s: str) -> str:
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().upper()


# Orçamentos mensais opcionais: ORCAMENTO_ALIMENTACAO=800
ORCAMENTOS: dict[str, float] = {}
for _cat in CATEGORIAS:
    _v = os.environ.get(f"ORCAMENTO_{_norm(_cat)}")
    if _v:
        try:
            ORCAMENTOS[_cat] = float(_v)
        except ValueError:
            pass

# ── Google Sheets ─────────────────────────────────────────────────────────

CABECALHO = ["Data", "Descrição", "Categoria", "Valor", "Tipo", "Mês/Ano", "Observação"]

_sheet_cache: tuple | None = None  # (spreadsheet, expira_em)


def get_spreadsheet():
    global _sheet_cache
    now = datetime.now()
    if _sheet_cache and now < _sheet_cache[1]:
        return _sheet_cache[0]
    creds = Credentials(
        token=None,
        refresh_token=GOOGLE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    creds.refresh(Request())
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(GOOGLE_SHEETS_ID)
    _sheet_cache = (spreadsheet, now + timedelta(minutes=5))
    return spreadsheet


def get_or_create_monthly_sheet(spreadsheet, mes_ano: str):
    try:
        return spreadsheet.worksheet(mes_ano)
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=mes_ano, rows=1000, cols=10)
        sheet.append_row(CABECALHO, value_input_option="USER_ENTERED")
        return sheet


def add_row(data: str, descricao: str, categoria: str, valor: float, tipo: str, obs: str = ""):
    mes_ano = datetime.strptime(data, "%d/%m/%Y").strftime("%m/%Y") if data else datetime.now().strftime("%m/%Y")
    spreadsheet = get_spreadsheet()
    sheet = get_or_create_monthly_sheet(spreadsheet, mes_ano)
    sheet.append_row(
        [data, descricao, categoria, valor, tipo, mes_ano, obs],
        value_input_option="USER_ENTERED",
    )


def _soma_rows(rows: list, tipo: str) -> float:
    return sum(
        float(str(r[3]).replace(",", "."))
        for r in rows
        if len(r) > 4 and r[4] == tipo and r[3]
    )


# ── OCR com GPT-4o Vision ─────────────────────────────────────────────────

def extract_receipt_data(image_bytes: bytes) -> dict | None:
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    prompt = f"""Você é um assistente especialista em extrair dados de comprovantes, notas fiscais e recibos brasileiros.

Analise a imagem e extraia as seguintes informações em JSON:
{{
  "data": "DD/MM/AAAA",
  "valor": <número float, ex: 150.00>,
  "descricao": "<nome do estabelecimento ou descrição breve>",
  "categoria": "<uma das opções abaixo>",
  "tipo": "<Despesa ou Receita>",
  "observacao": "<informação extra relevante, ou string vazia>"
}}

Categorias disponíveis: {", ".join(CATEGORIAS)}

Regras:
- Se não conseguir identificar a data, use a data de hoje: {datetime.now().strftime("%d/%m/%Y")}
- Se não conseguir identificar o valor, use null
- Escolha a categoria mais adequada; use "Outros" como fallback
- Receitas (salário, Pix recebido, etc.) → tipo = "Receita"; demais → "Despesa"
- Responda SOMENTE com o JSON, sem texto adicional."""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            max_tokens=512,
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        return json.loads(raw)
    except Exception as e:
        logger.error("Erro ao chamar OpenAI: %s", e)
        return None


# ── Helpers ───────────────────────────────────────────────────────────────

def is_allowed(update: Update) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return update.effective_user.id in ALLOWED_USER_IDS


def _confirmacao_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirmar",        callback_data="confirmar"),
            InlineKeyboardButton("✏️ Editar categoria", callback_data="editar_cat"),
        ],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")],
    ])


def _edicao_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Descrição", callback_data="edit_campo_descricao"),
            InlineKeyboardButton("💰 Valor",      callback_data="edit_campo_valor"),
        ],
        [
            InlineKeyboardButton("🏷️ Categoria",  callback_data="edit_campo_categoria"),
            InlineKeyboardButton("📅 Data",        callback_data="edit_campo_data"),
        ],
        [
            InlineKeyboardButton("✅ Salvar",  callback_data="edit_salvar"),
            InlineKeyboardButton("❌ Cancelar", callback_data="edit_cancelar"),
        ],
    ])


def _texto_pendente(d: dict) -> str:
    valor_fmt = f"R$ {float(d.get('valor', 0)):,.2f}"
    return (
        f"📋 *Dados:*\n\n"
        f"📅 Data: `{d.get('data', '?')}`\n"
        f"📝 Descrição: `{d.get('descricao', '?')}`\n"
        f"🏷️ Categoria: `{d.get('categoria', '?')}`\n"
        f"💰 Valor: `{valor_fmt}`\n"
        f"🔄 Tipo: `{d.get('tipo', '?')}`\n\n"
        f"Confirmar?"
    )


def _texto_edicao(d: dict) -> str:
    valor_fmt = f"R$ {float(d.get('valor', 0)):,.2f}"
    return (
        f"✏️ *Editando lançamento:*\n\n"
        f"📅 Data: `{d.get('data', '?')}`\n"
        f"📝 Descrição: `{d.get('descricao', '?')}`\n"
        f"🏷️ Categoria: `{d.get('categoria', '?')}`\n"
        f"💰 Valor: `{valor_fmt}`\n"
        f"🔄 Tipo: `{d.get('tipo', '?')}`\n\n"
        f"Selecione o campo para editar ou salve."
    )


def _parse_lancamento(text: str) -> dict | None:
    """Extrai dados de lançamento de texto puro. Retorna dict pendente ou None."""
    parts = text.split()

    # Detecta data opcional DD/MM/AAAA
    data_pattern = re.compile(r"^\d{2}/\d{2}/\d{4}$")
    data_lancamento = None
    parts_sem_data = []
    for p in parts:
        if data_pattern.match(p) and data_lancamento is None:
            try:
                datetime.strptime(p, "%d/%m/%Y")
                data_lancamento = p
                continue
            except ValueError:
                pass
        parts_sem_data.append(p)
    if data_lancamento is None:
        data_lancamento = datetime.now().strftime("%d/%m/%Y")

    # Extrai valor (primeiro número encontrado)
    valor = None
    valor_idx = None
    for i, p in enumerate(parts_sem_data):
        try:
            valor = float(p.replace(",", "."))
            valor_idx = i
            break
        except ValueError:
            continue

    if valor is None:
        return None

    descricao     = " ".join(parts_sem_data[:valor_idx]) if valor_idx > 0 else "Sem descrição"
    categoria_raw = " ".join(parts_sem_data[valor_idx + 1:]).strip()
    categoria     = next((c for c in CATEGORIAS if c.lower() == categoria_raw.lower()), "Outros")
    tipo          = "Receita" if categoria == "Receita" else "Despesa"

    return {
        "data":       data_lancamento,
        "descricao":  descricao,
        "categoria":  categoria,
        "valor":      valor,
        "tipo":       tipo,
        "observacao": "",
    }


def _gerar_resumo_periodo(limite: datetime, hoje: datetime) -> str:
    """Gera texto de resumo para um intervalo de datas. Reutilizado por /semanal e pelo job."""
    spreadsheet      = get_spreadsheet()
    mes_pattern      = re.compile(r"^\d{2}/\d{4}$")
    meses_relevantes = {hoje.strftime("%m/%Y"), limite.strftime("%m/%Y")}

    rows_filtradas = []
    for ws in spreadsheet.worksheets():
        if not mes_pattern.match(ws.title) or ws.title not in meses_relevantes:
            continue
        for r in ws.get_all_values()[1:]:
            if len(r) > 4 and r[0] and r[3]:
                try:
                    data_row = datetime.strptime(r[0], "%d/%m/%Y")
                    if limite <= data_row <= hoje:
                        rows_filtradas.append(r)
                except ValueError:
                    continue

    if not rows_filtradas:
        return f"📅 *Últimos 7 dias* ({limite.strftime('%d/%m')} – {hoje.strftime('%d/%m')})\n\nNenhum lançamento no período."

    cat_despesa = defaultdict(float)
    receitas = 0.0
    for r in rows_filtradas:
        val = float(str(r[3]).replace(",", "."))
        if r[4] == "Receita":
            receitas += val
        else:
            cat_despesa[r[2]] += val

    total_despesas = sum(cat_despesa.values())
    saldo_val      = receitas - total_despesas
    sinal          = "🟢" if saldo_val >= 0 else "🔴"

    linhas = [f"📅 *Últimos 7 dias* ({limite.strftime('%d/%m')} – {hoje.strftime('%d/%m')})\n"]
    if receitas:
        linhas.append(f"✅ Receitas: R$ {receitas:,.2f}")
    if cat_despesa:
        linhas.append("❌ *Despesas por categoria:*")
        for cat, val in sorted(cat_despesa.items(), key=lambda x: -x[1]):
            linhas.append(f"  • {cat}: R$ {val:,.2f}")
        linhas.append(f"\n💸 Total: R$ {total_despesas:,.2f}")
    linhas.append(f"{sinal} Saldo: R$ {saldo_val:,.2f}")
    return "\n".join(linhas)


async def _checar_orcamento(query, categoria: str, mes_ano: str):
    if categoria not in ORCAMENTOS:
        return
    try:
        spreadsheet = get_spreadsheet()
        ws = spreadsheet.worksheet(mes_ano)
        rows = ws.get_all_values()[1:]
        total_cat = sum(
            float(str(r[3]).replace(",", "."))
            for r in rows
            if len(r) > 4 and r[2] == categoria and r[4] == "Despesa" and r[3]
        )
        limite = ORCAMENTOS[categoria]
        pct = total_cat / limite * 100
        if pct >= 100:
            await query.message.reply_text(
                f"🚨 *Orçamento estourado: {categoria}*\n"
                f"Gasto: R$ {total_cat:,.2f} | Limite: R$ {limite:,.2f} ({pct:.0f}%)",
                parse_mode="Markdown",
            )
        elif pct >= 80:
            await query.message.reply_text(
                f"⚠️ *Atenção: {categoria}*\n"
                f"Você atingiu {pct:.0f}% do orçamento mensal.\n"
                f"Gasto: R$ {total_cat:,.2f} | Limite: R$ {limite:,.2f}",
                parse_mode="Markdown",
            )
    except Exception:
        pass


def _ultimo_lancamento_info():
    """Retorna (ws, row_idx, row_data) do último lançamento ou (None, None, None)."""
    spreadsheet = get_spreadsheet()
    mes_pattern = re.compile(r"^\d{2}/\d{4}$")
    monthly_sheets = sorted(
        [ws for ws in spreadsheet.worksheets() if mes_pattern.match(ws.title)],
        key=lambda ws: datetime.strptime(ws.title, "%m/%Y"),
    )
    for ws in reversed(monthly_sheets):
        all_rows  = ws.get_all_values()
        data_rows = [(i + 1, r) for i, r in enumerate(all_rows) if any(r) and i > 0]
        if data_rows:
            row_idx, row = data_rows[-1]
            return ws, row_idx, row
    return None, None, None


# ── Handlers do Bot ───────────────────────────────────────────────────────

async def start(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Olá! Sou seu assistente de Controle Financeiro.*\n\n"
        "📸 *Foto:* tire uma foto do comprovante\n"
        "🎙️ *Voz:* diga o gasto em áudio\n"
        "✍️ *Texto:* `Mercado 150,00 Alimentação`\n\n"
        "Comandos: /ajuda · /ultimo · /saldo",
        parse_mode="Markdown",
    )


async def ajuda(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Comandos disponíveis:*\n\n"
        "/start – Apresentação\n"
        "/ajuda – Esta mensagem\n"
        "/ultimo – Último lançamento registrado\n"
        "/deletar – Apagar o último lançamento\n"
        "/editar – Corrigir o último lançamento\n"
        "/saldo – Total geral (todos os meses)\n"
        "/resumomes – Mês atual por categoria\n"
        "/resumomes MM/AAAA – Mês específico\n"
        "/resumoanual – Ano atual, mês a mês\n"
        "/semanal – Últimos 7 dias\n"
        "/exportar – CSV do mês atual\n"
        "/exportar MM/AAAA – CSV de mês específico\n\n"
        "📸 *Foto:* envie qualquer comprovante\n"
        "🎙️ *Voz:* diga o gasto (ex: _'farmácia quarenta e cinco reais saúde'_)\n"
        "✍️ *Texto:* `<descrição> <valor> [categoria] [DD/MM/AAAA]`\n"
        "    Ex: `Farmácia 45,50 Saúde 20/03/2026`",
        parse_mode="Markdown",
    )


async def ultimo(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    try:
        _, _, row = _ultimo_lancamento_info()
        if row is None:
            await update.message.reply_text("Nenhum lançamento encontrado ainda.")
            return
        await update.message.reply_text(
            f"📌 *Último lançamento:*\n"
            f"📅 Data: {row[0]}\n"
            f"📝 Descrição: {row[1]}\n"
            f"🏷️ Categoria: {row[2]}\n"
            f"💰 Valor: R$ {row[3]}\n"
            f"🔄 Tipo: {row[4]}",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"Erro ao buscar dados: {e}")


async def deletar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    try:
        target_ws, row_idx, row = _ultimo_lancamento_info()
        if row is None:
            await update.message.reply_text("Nenhum lançamento encontrado para apagar.")
            return
        context.user_data["deletar_info"] = {"sheet_title": target_ws.title, "row_idx": row_idx}
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🗑️ Confirmar exclusão", callback_data="deletar_confirmar"),
            InlineKeyboardButton("❌ Cancelar",            callback_data="deletar_cancelar"),
        ]])
        await update.message.reply_text(
            f"⚠️ *Apagar este lançamento?*\n\n"
            f"📅 Data: {row[0]}\n"
            f"📝 Descrição: {row[1]}\n"
            f"🏷️ Categoria: {row[2]}\n"
            f"💰 Valor: R$ {row[3]}\n"
            f"🔄 Tipo: {row[4]}",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"Erro ao buscar lançamento: {e}")


async def editar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra o último lançamento e permite editar campo a campo."""
    if not is_allowed(update):
        return
    try:
        target_ws, row_idx, row = _ultimo_lancamento_info()
        if row is None:
            await update.message.reply_text("Nenhum lançamento encontrado para editar.")
            return
        dados = {
            "data":       row[0],
            "descricao":  row[1],
            "categoria":  row[2],
            "valor":      row[3],
            "tipo":       row[4],
            "observacao": row[6] if len(row) > 6 else "",
        }
        context.user_data["editar_info"] = {
            "sheet_title": target_ws.title,
            "row_idx":     row_idx,
            "dados":       dados,
            "campo":       None,
        }
        await update.message.reply_text(
            _texto_edicao(dados),
            reply_markup=_edicao_keyboard(),
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"Erro ao buscar lançamento: {e}")


async def saldo(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    try:
        spreadsheet = get_spreadsheet()
        mes_pattern = re.compile(r"^\d{2}/\d{4}$")
        receitas = 0.0
        despesas = 0.0
        for ws in spreadsheet.worksheets():
            if not mes_pattern.match(ws.title):
                continue
            rows = ws.get_all_values()[1:]
            receitas += _soma_rows(rows, "Receita")
            despesas += _soma_rows(rows, "Despesa")
        saldo_val = receitas - despesas
        sinal = "🟢" if saldo_val >= 0 else "🔴"
        await update.message.reply_text(
            f"📊 *Resumo financeiro (todos os meses):*\n\n"
            f"✅ Receitas:  R$ {receitas:,.2f}\n"
            f"❌ Despesas: R$ {despesas:,.2f}\n"
            f"{sinal} Saldo:     R$ {saldo_val:,.2f}",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"Erro ao calcular saldo: {e}")


async def exportar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Envia CSV do mês. Uso: /exportar ou /exportar MM/AAAA"""
    if not is_allowed(update):
        return
    try:
        if context.args:
            mes_ano = context.args[0]
            try:
                datetime.strptime(mes_ano, "%m/%Y")
            except ValueError:
                await update.message.reply_text(
                    "Formato inválido. Use: `/exportar MM/AAAA`",
                    parse_mode="Markdown",
                )
                return
        else:
            mes_ano = datetime.now().strftime("%m/%Y")

        spreadsheet = get_spreadsheet()
        try:
            ws = spreadsheet.worksheet(mes_ano)
        except gspread.WorksheetNotFound:
            await update.message.reply_text(f"Sem dados para {mes_ano}.")
            return

        rows   = ws.get_all_values()
        output = io.StringIO()
        csv.writer(output).writerows(rows)
        csv_bytes = output.getvalue().encode("utf-8-sig")  # BOM para compatibilidade com Excel
        filename  = f"financas_{mes_ano.replace('/', '-')}.csv"

        await update.message.reply_document(document=csv_bytes, filename=filename)
    except Exception as e:
        await update.message.reply_text(f"Erro ao exportar: {e}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("⛔ Acesso não autorizado.")
        return

    msg       = await update.message.reply_text("🔍 Analisando comprovante com IA…")
    photo     = update.message.photo[-1]
    file      = await context.bot.get_file(photo.file_id)
    resp      = requests.get(file.file_path, timeout=30)
    img_bytes = resp.content

    data = extract_receipt_data(img_bytes)
    if not data or data.get("valor") is None:
        await msg.edit_text(
            "❌ Não consegui extrair os dados.\n"
            "Tente uma foto mais nítida ou envie os dados em texto:\n"
            "`<descrição> <valor> [categoria]`",
            parse_mode="Markdown",
        )
        return

    context.user_data["pendente"] = data
    await msg.edit_text(
        _texto_pendente(data),
        reply_markup=_confirmacao_keyboard(),
        parse_mode="Markdown",
    )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Transcreve mensagem de voz via Whisper e inicia fluxo de confirmação."""
    if not is_allowed(update):
        await update.message.reply_text("⛔ Acesso não autorizado.")
        return

    msg  = await update.message.reply_text("🎙️ Transcrevendo áudio…")
    file = await context.bot.get_file(update.message.voice.file_id)
    resp = requests.get(file.file_path, timeout=30)

    audio_bytes      = io.BytesIO(resp.content)
    audio_bytes.name = "audio.ogg"

    try:
        transcricao = openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_bytes,
            language="pt",
        )
        texto = transcricao.text.strip()
    except Exception as e:
        logger.error("Erro ao transcrever áudio: %s", e)
        await msg.edit_text("❌ Não consegui transcrever o áudio. Tente novamente.")
        return

    pendente = _parse_lancamento(texto)
    if not pendente:
        await msg.edit_text(
            f'🎙️ Entendi: _"{texto}"_\n\n'
            f"Mas não consegui identificar um valor.\n"
            f'Tente: _"Farmácia quarenta e cinco reais saúde"_',
            parse_mode="Markdown",
        )
        return

    context.user_data["pendente"] = pendente
    await msg.edit_text(
        f'🎙️ _"{texto}"_\n\n' + _texto_pendente(pendente),
        reply_markup=_confirmacao_keyboard(),
        parse_mode="Markdown",
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Aceita lançamento em texto ou resposta a fluxo de edição."""
    if not is_allowed(update):
        return

    text = update.message.text.strip()
    if text.startswith("/"):
        return

    # ── Resposta a um campo em edição ────────────────────────────────────
    editar_info = context.user_data.get("editar_info")
    if editar_info and editar_info.get("campo"):
        campo = editar_info["campo"]
        dados = editar_info["dados"]

        if campo == "valor":
            try:
                dados["valor"] = float(text.replace(",", "."))
            except ValueError:
                await update.message.reply_text("Valor inválido. Digite apenas o número, ex: `45,50`", parse_mode="Markdown")
                return
        elif campo == "data":
            try:
                datetime.strptime(text, "%d/%m/%Y")
                dados["data"] = text
            except ValueError:
                await update.message.reply_text("Data inválida. Use o formato `DD/MM/AAAA`", parse_mode="Markdown")
                return
        else:  # descricao
            dados[campo] = text

        editar_info["campo"] = None
        await update.message.reply_text(
            _texto_edicao(dados),
            reply_markup=_edicao_keyboard(),
            parse_mode="Markdown",
        )
        return

    # ── Novo lançamento por texto ─────────────────────────────────────────
    pendente = _parse_lancamento(text)
    if not pendente:
        await update.message.reply_text(
            "Não entendi 😕\nFormato: `<descrição> <valor> [categoria] [DD/MM/AAAA]`\n"
            "Ex: `Farmácia 45,50 Saúde 20/03/2026`",
            parse_mode="Markdown",
        )
        return

    context.user_data["pendente"] = pendente
    await update.message.reply_text(
        _texto_pendente(pendente),
        reply_markup=_confirmacao_keyboard(),
        parse_mode="Markdown",
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    action = query.data

    # ── Confirmar lançamento ──────────────────────────────────────────────
    if action == "confirmar":
        d = context.user_data.get("pendente")
        if not d:
            await query.edit_message_text("Dados expirados. Envie o comprovante novamente.")
            return
        try:
            data_salva = d.get("data", datetime.now().strftime("%d/%m/%Y"))
            categoria  = d.get("categoria", "Outros")
            add_row(
                data=data_salva,
                descricao=d.get("descricao", ""),
                categoria=categoria,
                valor=float(d.get("valor", 0)),
                tipo=d.get("tipo", "Despesa"),
                obs=d.get("observacao", ""),
            )
            context.user_data.pop("pendente", None)
            await query.edit_message_text(
                f"✅ *Lançamento salvo!*\n\n"
                f"📝 {d['descricao']} – R$ {float(d['valor']):,.2f}\n"
                f"🏷️ {categoria} | {d['tipo']}",
                parse_mode="Markdown",
            )
            if d.get("tipo") == "Despesa":
                mes_ano = datetime.strptime(data_salva, "%d/%m/%Y").strftime("%m/%Y")
                await _checar_orcamento(query, categoria, mes_ano)
        except Exception as e:
            logger.error("Erro ao salvar: %s", e)
            await query.edit_message_text(f"❌ Erro ao salvar: {e}")

    # ── Editar categoria (fluxo de novo lançamento) ───────────────────────
    elif action == "editar_cat":
        botoes = [[InlineKeyboardButton(cat, callback_data=f"cat_{cat}")] for cat in CATEGORIAS]
        await query.edit_message_text("Escolha a categoria correta:", reply_markup=InlineKeyboardMarkup(botoes))

    elif action.startswith("cat_"):
        nova_cat = action[4:]
        d = context.user_data.get("pendente", {})
        d["categoria"] = nova_cat
        d["tipo"]      = "Receita" if nova_cat == "Receita" else "Despesa"
        context.user_data["pendente"] = d
        await query.edit_message_text(_texto_pendente(d), reply_markup=_confirmacao_keyboard(), parse_mode="Markdown")

    # ── Cancelar lançamento ───────────────────────────────────────────────
    elif action == "cancelar":
        context.user_data.pop("pendente", None)
        await query.edit_message_text("❌ Lançamento cancelado.")

    # ── Confirmar exclusão ────────────────────────────────────────────────
    elif action == "deletar_confirmar":
        info = context.user_data.get("deletar_info")
        if not info:
            await query.edit_message_text("Operação expirada. Use /deletar novamente.")
            return
        try:
            spreadsheet = get_spreadsheet()
            ws = spreadsheet.worksheet(info["sheet_title"])
            ws.delete_rows(info["row_idx"])
            context.user_data.pop("deletar_info", None)
            await query.edit_message_text("🗑️ Lançamento apagado com sucesso.")
        except Exception as e:
            logger.error("Erro ao deletar: %s", e)
            await query.edit_message_text(f"❌ Erro ao apagar: {e}")

    elif action == "deletar_cancelar":
        context.user_data.pop("deletar_info", None)
        await query.edit_message_text("Operação cancelada.")

    # ── Fluxo de edição ───────────────────────────────────────────────────
    elif action.startswith("edit_campo_"):
        campo = action[len("edit_campo_"):]
        editar_info = context.user_data.get("editar_info")
        if not editar_info:
            await query.edit_message_text("Operação expirada. Use /editar novamente.")
            return

        if campo == "categoria":
            # Usa botões inline para categoria
            botoes = [[InlineKeyboardButton(cat, callback_data=f"edit_cat_{cat}")] for cat in CATEGORIAS]
            await query.edit_message_text("Escolha a nova categoria:", reply_markup=InlineKeyboardMarkup(botoes))
        else:
            editar_info["campo"] = campo
            prompts = {
                "descricao": "Digite a nova descrição:",
                "valor":     "Digite o novo valor (ex: `45,50`):",
                "data":      "Digite a nova data (ex: `20/03/2026`):",
            }
            await query.edit_message_text(prompts[campo], parse_mode="Markdown")

    elif action.startswith("edit_cat_"):
        nova_cat = action[len("edit_cat_"):]
        editar_info = context.user_data.get("editar_info")
        if not editar_info:
            await query.edit_message_text("Operação expirada. Use /editar novamente.")
            return
        editar_info["dados"]["categoria"] = nova_cat
        editar_info["dados"]["tipo"]      = "Receita" if nova_cat == "Receita" else "Despesa"
        await query.edit_message_text(
            _texto_edicao(editar_info["dados"]),
            reply_markup=_edicao_keyboard(),
            parse_mode="Markdown",
        )

    elif action == "edit_salvar":
        editar_info = context.user_data.get("editar_info")
        if not editar_info:
            await query.edit_message_text("Operação expirada. Use /editar novamente.")
            return
        try:
            spreadsheet = get_spreadsheet()
            ws = spreadsheet.worksheet(editar_info["sheet_title"])
            ws.delete_rows(editar_info["row_idx"])
            d = editar_info["dados"]
            add_row(
                data=d.get("data", datetime.now().strftime("%d/%m/%Y")),
                descricao=d.get("descricao", ""),
                categoria=d.get("categoria", "Outros"),
                valor=float(str(d.get("valor", 0)).replace(",", ".")),
                tipo=d.get("tipo", "Despesa"),
                obs=d.get("observacao", ""),
            )
            context.user_data.pop("editar_info", None)
            await query.edit_message_text(
                f"✅ *Lançamento atualizado!*\n\n"
                f"📝 {d['descricao']} – R$ {float(str(d['valor']).replace(',','.')):,.2f}\n"
                f"🏷️ {d['categoria']} | {d['tipo']}",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error("Erro ao editar: %s", e)
            await query.edit_message_text(f"❌ Erro ao salvar edição: {e}")

    elif action == "edit_cancelar":
        context.user_data.pop("editar_info", None)
        await query.edit_message_text("Edição cancelada.")


# ── Handlers de Resumo ────────────────────────────────────────────────────

async def resumomes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    try:
        if context.args:
            mes_ano = context.args[0]
            try:
                datetime.strptime(mes_ano, "%m/%Y")
            except ValueError:
                await update.message.reply_text(
                    "Formato inválido. Use: `/resumomes MM/AAAA`\nEx: `/resumomes 03/2026`",
                    parse_mode="Markdown",
                )
                return
        else:
            mes_ano = datetime.now().strftime("%m/%Y")

        spreadsheet = get_spreadsheet()
        try:
            ws = spreadsheet.worksheet(mes_ano)
        except gspread.WorksheetNotFound:
            await update.message.reply_text(f"Nenhum lançamento encontrado para {mes_ano}.")
            return

        rows = ws.get_all_values()[1:]
        if not rows or not any(any(r) for r in rows):
            await update.message.reply_text(f"Nenhum lançamento em {mes_ano}.")
            return

        cat_despesa = defaultdict(float)
        receitas = 0.0
        for r in rows:
            if len(r) > 4 and r[3]:
                val = float(str(r[3]).replace(",", "."))
                if r[4] == "Receita":
                    receitas += val
                else:
                    cat_despesa[r[2]] += val

        total_despesas = sum(cat_despesa.values())
        saldo_val      = receitas - total_despesas
        sinal          = "🟢" if saldo_val >= 0 else "🔴"

        # Comparação com mês anterior
        dt_atual = datetime.strptime(mes_ano, "%m/%Y")
        dt_prev  = (dt_atual.replace(day=1) - timedelta(days=1)).replace(day=1)
        prev_mes_ano    = dt_prev.strftime("%m/%Y")
        prev_desp_total = None
        try:
            prev_ws         = spreadsheet.worksheet(prev_mes_ano)
            prev_rows       = prev_ws.get_all_values()[1:]
            prev_desp_total = _soma_rows(prev_rows, "Despesa")
        except gspread.WorksheetNotFound:
            pass

        linhas = [f"📅 *Resumo de {mes_ano}*\n"]
        if receitas:
            linhas.append(f"✅ Receitas: R$ {receitas:,.2f}\n")
        if cat_despesa:
            linhas.append("❌ *Despesas por categoria:*")
            for cat, val in sorted(cat_despesa.items(), key=lambda x: -x[1]):
                linha = f"  • {cat}: R$ {val:,.2f}"
                if cat in ORCAMENTOS:
                    pct = val / ORCAMENTOS[cat] * 100
                    linha += f"  _{pct:.0f}% do limite_"
                linhas.append(linha)

            if prev_desp_total and prev_desp_total > 0:
                diff_pct = (total_despesas - prev_desp_total) / prev_desp_total * 100
                seta = "↑" if diff_pct > 0 else "↓"
                linhas.append(f"\n💸 Total despesas: R$ {total_despesas:,.2f}  {seta} {abs(diff_pct):.0f}% vs {prev_mes_ano}")
            else:
                linhas.append(f"\n💸 Total despesas: R$ {total_despesas:,.2f}")

        linhas.append(f"{sinal} Saldo: R$ {saldo_val:,.2f}")
        await update.message.reply_text("\n".join(linhas), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Erro ao gerar resumo: {e}")


async def resumoanual(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    try:
        ano = datetime.now().strftime("%Y")
        spreadsheet = get_spreadsheet()
        mes_pattern = re.compile(rf"^\d{{2}}/{ano}$")
        monthly_sheets = sorted(
            [ws for ws in spreadsheet.worksheets() if mes_pattern.match(ws.title)],
            key=lambda ws: datetime.strptime(ws.title, "%m/%Y"),
        )
        if not monthly_sheets:
            await update.message.reply_text(f"Nenhum lançamento encontrado em {ano}.")
            return

        total_receitas = 0.0
        total_despesas = 0.0
        linhas = [f"📊 *Resumo anual {ano}*\n"]
        for ws in monthly_sheets:
            rows = ws.get_all_values()[1:]
            rec  = _soma_rows(rows, "Receita")
            desp = _soma_rows(rows, "Despesa")
            saldo = rec - desp
            sinal = "🟢" if saldo >= 0 else "🔴"
            linhas.append(f"{sinal} *{ws.title}*  R$ {saldo:+,.2f}   _(+{rec:,.2f} / -{desp:,.2f})_")
            total_receitas += rec
            total_despesas += desp

        saldo_total = total_receitas - total_despesas
        sinal_total = "🟢" if saldo_total >= 0 else "🔴"
        linhas.append(f"\n{sinal_total} *Total {ano}*: R$ {saldo_total:,.2f}")
        linhas.append(f"  ✅ Receitas:  R$ {total_receitas:,.2f}")
        linhas.append(f"  ❌ Despesas: R$ {total_despesas:,.2f}")
        await update.message.reply_text("\n".join(linhas), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Erro ao gerar resumo anual: {e}")


async def semanal(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    try:
        hoje   = datetime.now().replace(hour=23, minute=59, second=59)
        limite = hoje - timedelta(days=7)
        texto  = _gerar_resumo_periodo(limite, hoje)
        await update.message.reply_text(texto, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Erro ao gerar resumo semanal: {e}")


# ── Job: notificação automática semanal ──────────────────────────────────

async def _job_resumo_semanal(context: ContextTypes.DEFAULT_TYPE):
    ids = NOTIFY_USER_IDS or ALLOWED_USER_IDS
    if not ids:
        logger.warning("Notificação semanal: nenhum NOTIFY_USER_IDS ou ALLOWED_USER_IDS configurado.")
        return
    try:
        hoje   = datetime.now().replace(hour=23, minute=59, second=59)
        limite = hoje - timedelta(days=7)
        texto  = _gerar_resumo_periodo(limite, hoje)
    except Exception as e:
        logger.error("Erro ao gerar resumo semanal automático: %s", e)
        return
    for uid in ids:
        try:
            await context.bot.send_message(chat_id=uid, text=texto, parse_mode="Markdown")
        except Exception as e:
            logger.warning("Falha ao notificar %s: %s", uid, e)


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("ajuda",       ajuda))
    app.add_handler(CommandHandler("ultimo",      ultimo))
    app.add_handler(CommandHandler("deletar",     deletar))
    app.add_handler(CommandHandler("editar",      editar))
    app.add_handler(CommandHandler("saldo",       saldo))
    app.add_handler(CommandHandler("exportar",    exportar))
    app.add_handler(CommandHandler("resumomes",   resumomes))
    app.add_handler(CommandHandler("resumoanual", resumoanual))
    app.add_handler(CommandHandler("semanal",     semanal))
    app.add_handler(MessageHandler(filters.PHOTO,                   handle_photo))
    app.add_handler(MessageHandler(filters.VOICE,                   handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Notificação automática: toda segunda-feira às 9h (horário de Brasília)
    app.job_queue.run_daily(
        _job_resumo_semanal,
        time=dt_time(9, 0, tzinfo=BRT),
        days=(0,),  # 0 = segunda-feira
    )

    logger.info("Bot iniciado — aguardando mensagens...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
