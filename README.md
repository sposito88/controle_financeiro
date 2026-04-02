# 🤖 Controle Financeiro Inteligente (Telegram Bot)

Um bot para Telegram que automatiza o seu controle financeiro usando Inteligência Artificial. Em vez de abrir planilhas e preencher formulários chatos, basta enviar uma foto do seu recibo ou nota fiscal pelo Telegram, e nossa IA (OpenAI GPT-4o Vision) extrai as informações estruturadas diretamente para o seu Google Sheets.

## ✨ Como funciona?

1. **Tire uma foto**: Envie a foto de um recibo, cupom fiscal ou nota para o bot no Telegram.
2. **Análise por IA**: O GPT-4o Vision analisa a imagem, identificando nome do estabelecimento, valor, data e sugere a categoria correta.
3. **Confirmação rápida**: O bot exibe os dados no Telegram com botões interativos para você conferir ou editar a categoria, se necessário.
4. **Google Sheets**: Com apenas um clique, o gasto é salvo automaticamente como uma nova linha na sua planilha financeira!

Você também pode enviar gastos por **texto simples** (ex: `Uber 18,90` ou `Supermercado 230 Alimentação`) caso não tenha a foto!

## 🛠️ Tecnologias Utilizadas

- **Python 3.10+**: Linguagem base do sistema.
- **python-telegram-bot**: Interface de comunicação com a API do Telegram v21.6.
- **OpenAI GPT-4o Vision**: Para reconhecimento e processamento avançado de imagem via IA.
- **gspread & Google OAuth2**: Para leitura e gravação assíncrona/direta na planilha do Google Sheets.

## 🚀 Como rodar o projeto

### Pré-requisitos
1. Uma conta no Telegram e um bot criado via [@BotFather](https://t.me/botfather)
2. Uma conta na OpenAI com créditos ativados.
3. Um projeto no Google Cloud Console com as APIs de Google Sheets e Google Drive habilitadas, bem como credenciais OAuth2.
4. Python instalado em sua máquina ou servidor.

### Passo a passo (Resumo)
Para o guia detalhado e passo a passo de configuração desde o zero de cada um dos tokens, veja o [SETUP.md](SETUP.md).

1. Clone o repositório:
```bash
git clone https://github.com/sposito88/controle_financeiro.git
cd controle_financeiro
```

2. Instale as dependências:
```bash
pip install -r requirements.txt
```

3. Crie o arquivo `.env` na raiz do projeto contendo as seguintes chaves (use o `.env.example` como base):
```env
TELEGRAM_TOKEN=seu_token_telegram
OPENAI_API_KEY=sua_chave_openai
GOOGLE_SHEETS_ID=id_da_sua_planilha
GOOGLE_CLIENT_ID=seu_client_id
GOOGLE_CLIENT_SECRET=seu_client_secret
GOOGLE_REFRESH_TOKEN=seu_refresh_token
ALLOWED_USER_IDS=seu_id_telegram # opcional, lista de IDs separados por vírgula para restringir acesso
```

4. Execute o bot:
```bash
python bot.py
```

## 📊 Estrutura da Planilha

Para que a integração funcione, você precisa de uma aba chamada **Lançamentos** em seu Google Sheets, contendo a seguinte ordem de colunas:
| A | B | C | D | E | F | G |
| - | - | - | - | - | - | - |
| Data | Descrição | Categoria | Valor | Tipo | Mês/Ano | Observação |

## 📚 Documentação Adicional

Para entender toda a lógica por trás do sistema, processo de prompt e arquitetura de código, consulte a [Documentação Detalhada (SISTEMA_DETALHADO.md)](SISTEMA_DETALHADO.md).

---
Criado para facilitar a vida financeira sem fricções! 💸
