# 🤖 Bot de Controle Financeiro — Guia de Configuração

## O que você vai precisar
- Python 3.10+
- Conta no Telegram
- Conta na OpenAI (para GPT-4o Vision)
- Conta Google com Google Sheets

---

## PASSO 1 — Criar o Bot no Telegram

1. Abra o Telegram e procure por **@BotFather**
2. Envie `/newbot` e siga as instruções
3. Copie o **token** gerado (ex: `123456:ABC-DEF...`)

---

## PASSO 2 — Obter a chave da OpenAI

1. Acesse [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Clique em **Create new secret key**
3. Copie a chave (começa com `sk-`)

> 💡 O bot usa o modelo **gpt-4o** para analisar imagens. O custo por comprovante é ~$0.002 (menos de 1 centavo).

---

## PASSO 3 — Configurar Google Sheets

### 3a. Subir a planilha
1. Abra [Google Drive](https://drive.google.com)
2. Faça upload do arquivo `Controle_Financeiro.xlsx`
3. Clique com o botão direito → **Abrir com Google Planilhas**
4. Copie o **ID** da planilha da URL:
   ```
   https://docs.google.com/spreadsheets/d/COPIE_ESTE_ID/edit
   ```

### 3b. Criar conta de serviço (para o bot escrever na planilha)
1. Acesse [console.cloud.google.com](https://console.cloud.google.com)
2. Crie um novo projeto (ou use um existente)
3. Ative a **Google Sheets API**:
   - Menu → APIs e Serviços → Biblioteca → busque "Sheets" → Ativar
4. Crie uma **Conta de Serviço**:
   - Menu → APIs e Serviços → Credenciais → Criar credencial → Conta de serviço
   - Dê um nome qualquer e conclua
5. Clique na conta criada → Aba **Chaves** → Adicionar chave → JSON
6. Salve o arquivo JSON como `credentials.json` na mesma pasta do bot

### 3c. Compartilhar a planilha com a conta de serviço
1. Abra o arquivo JSON e copie o valor de `"client_email"` (ex: `bot@projeto.iam.gserviceaccount.com`)
2. Abra a planilha no Google Sheets
3. Clique em **Compartilhar** → cole o e-mail da conta de serviço → permissão **Editor**

---

## PASSO 4 — Configurar o arquivo .env

1. Renomeie `.env.example` para `.env`
2. Preencha os valores:
   ```env
   TELEGRAM_TOKEN=seu_token_do_botfather
   OPENAI_API_KEY=sk-...
   GOOGLE_SHEETS_ID=id_da_planilha
   GOOGLE_CREDENTIALS_FILE=credentials.json
   ALLOWED_USER_IDS=seu_id_do_telegram
   ```
3. Para descobrir seu ID no Telegram, fale com [@userinfobot](https://t.me/userinfobot)

---

## PASSO 5 — Instalar e rodar o bot

```bash
# Instalar dependências
pip install -r requirements.txt

# Iniciar o bot
python bot.py
```

O bot fica rodando em segundo plano. Para manter ativo 24h, use um VPS, Raspberry Pi, ou serviços como **Railway**, **Render** ou **Google Cloud Run**.

---

## Como usar o bot

| Ação | Como fazer |
|------|-----------|
| Registrar comprovante | Envie uma **foto** para o bot |
| Registrar via texto | `Mercado 150,00 Alimentação` |
| Ver último lançamento | `/ultimo` |
| Ver saldo geral | `/saldo` |
| Ajuda | `/ajuda` |

### Categorias disponíveis
Alimentação · Transporte · Saúde · Educação · Lazer · Moradia · Vestuário · Receita · Outros

---

## Estrutura dos arquivos

```
📁 Controle financeiro/
├── bot.py                  ← Script principal do bot
├── credentials.json        ← Credenciais Google (você gera no Passo 3)
├── .env                    ← Suas chaves secretas (não compartilhe!)
├── .env.example            ← Modelo do .env
├── requirements.txt        ← Dependências Python
├── Controle_Financeiro.xlsx ← Planilha para importar no Google Sheets
└── SETUP.md                ← Este arquivo
```
