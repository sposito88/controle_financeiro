# Bot de Controle Financeiro com IA — Documentação Técnica Completa

## Visão Geral

Este projeto é um bot para Telegram que automatiza o registro de gastos e receitas financeiras. O usuário envia uma foto de um comprovante de compra, nota fiscal ou recibo diretamente pelo Telegram. O bot analisa a imagem usando inteligência artificial (GPT-4o Vision da OpenAI), extrai automaticamente as informações relevantes — data, valor, descrição e categoria — e salva tudo em uma planilha do Google Sheets, sem que o usuário precise digitar nada manualmente.

O bot também aceita lançamentos por texto simples, exibe o último lançamento registrado e mostra um resumo financeiro com total de receitas, despesas e saldo.

---

## O Problema que Ele Resolve

Manter um controle financeiro pessoal exige disciplina e consistência. O maior obstáculo não é a falta de vontade, mas o atrito: abrir um aplicativo, navegar até a planilha, digitar data, valor, categoria. Esse processo repetitivo faz com que a maioria das pessoas desista no meio do caminho.

Este bot elimina esse atrito. O fluxo se torna: tirar foto → enviar no Telegram → clicar em confirmar. Três ações, menos de 10 segundos.

---

## Tecnologias Utilizadas

### Python
Linguagem principal do projeto. Toda a lógica do bot está escrita em Python 3.10 ou superior.

### python-telegram-bot (versão 21.6)
Biblioteca que faz a comunicação com a API do Telegram. É responsável por receber mensagens, fotos e cliques em botões, além de enviar respostas ao usuário. Usa programação assíncrona com `async/await` para processar múltiplas interações ao mesmo tempo.

### OpenAI GPT-4o Vision
Modelo de inteligência artificial da OpenAI com capacidade de analisar imagens. Quando o usuário envia uma foto, o bot converte a imagem para o formato base64 e envia para a API da OpenAI junto com um prompt em português. O modelo retorna um JSON estruturado com os dados extraídos do comprovante.

### gspread (versão 6.0+)
Biblioteca Python que permite ler e escrever dados em planilhas do Google Sheets. O bot usa ela para adicionar uma nova linha na planilha sempre que um lançamento é confirmado.

### Google OAuth2
Sistema de autenticação do Google. O bot usa credenciais OAuth2 com refresh token para se autenticar na API do Google Sheets sem precisar que o usuário faça login manualmente. O token é renovado automaticamente a cada uso.

### python-dotenv
Carrega as variáveis de configuração (tokens, chaves de API, IDs) a partir de um arquivo `.env`, mantendo informações sensíveis fora do código-fonte.

---

## Arquitetura do Sistema

O sistema é composto por três camadas:

**1. Interface com o usuário — Telegram**
O Telegram funciona como a interface visual. O usuário interage pelo aplicativo que já usa no dia a dia. Não há necessidade de instalar nenhum outro app.

**2. Processamento inteligente — GPT-4o Vision (OpenAI)**
Toda a extração de dados das imagens acontece aqui. O modelo recebe a foto e devolve os dados estruturados em JSON.

**3. Armazenamento de dados — Google Sheets**
A planilha funciona como banco de dados. Cada lançamento vira uma linha nova. O usuário pode abrir a planilha no navegador, no celular, compartilhar com outra pessoa ou criar gráficos e filtros manualmente.

---

## Fluxo Completo de uma Transação por Foto

### Etapa 1 — Usuário envia a foto
O usuário abre o chat com o bot no Telegram e envia uma foto de um comprovante. Pode ser um cupom fiscal impresso, uma nota de supermercado, um recibo de farmácia ou qualquer documento que contenha valor e data.

### Etapa 2 — Download da imagem
O bot detecta que a mensagem contém uma foto. Ele seleciona automaticamente a versão de maior resolução disponível entre as versões que o Telegram armazena. Em seguida, faz o download dos bytes da imagem via HTTP com timeout de 30 segundos.

### Etapa 3 — Envio para o GPT-4o
A imagem é convertida para base64 (formato texto que pode ser enviado via API). O bot monta uma requisição para a API da OpenAI com:
- A imagem codificada em base64
- Um prompt em português descrevendo exatamente o que deve ser extraído
- Instrução para retornar SOMENTE um JSON, sem texto adicional
- Temperature igual a zero para garantir respostas determinísticas (sem variações criativas)
- Limite de 512 tokens na resposta

O prompt instrui o modelo a extrair: data no formato DD/MM/AAAA, valor numérico float, nome do estabelecimento ou descrição breve, categoria entre as 9 disponíveis, tipo (Despesa ou Receita) e uma observação opcional.

Se o modelo não conseguir identificar a data, ele usa a data de hoje como fallback. Se não conseguir identificar o valor, retorna null.

### Etapa 4 — Parsing da resposta
O bot recebe o texto retornado pela API. Como o modelo às vezes envolve o JSON em blocos de código markdown (```json ... ```), há um passo de limpeza com expressão regular para remover esses marcadores antes de fazer o parse do JSON.

### Etapa 5 — Exibição dos dados para confirmação
O bot edita a mensagem de "Analisando…" e exibe os dados extraídos formatados:
- Data detectada
- Descrição / nome do estabelecimento
- Categoria sugerida pela IA
- Valor formatado em reais
- Tipo (Despesa ou Receita)

Junto com os dados, aparecem três botões inline:
- **Confirmar** — salva o lançamento como está
- **Editar categoria** — abre um menu com as 9 categorias para o usuário escolher a correta
- **Cancelar** — descarta o lançamento sem salvar nada

Os dados ficam temporariamente armazenados em `context.user_data["pendente"]`, um dicionário em memória associado a cada usuário.

### Etapa 6 — Edição de categoria (opcional)
Se o usuário clicar em "Editar categoria", o bot exibe um teclado inline com os 9 botões de categoria. Ao selecionar uma categoria, o bot atualiza o dicionário em memória, recalcula o tipo (se a categoria for "Receita", o tipo muda para Receita; caso contrário, permanece Despesa) e exibe novamente os dados atualizados com os botões de Confirmar e Cancelar.

### Etapa 7 — Confirmação e gravação
Quando o usuário clica em "Confirmar", o bot chama a função de gravação no Google Sheets. Essa função:
1. Cria um objeto de credenciais OAuth2 com o refresh token salvo no `.env`
2. Renova automaticamente o access token chamando `creds.refresh(Request())`
3. Autentica no Google Sheets via `gspread.authorize(creds)`
4. Abre a planilha pelo ID e acessa a aba chamada "Lançamentos"
5. Adiciona uma nova linha com os campos: data, descrição, categoria, valor, tipo, mês/ano e observação

O campo mês/ano é calculado automaticamente a partir da data, no formato MM/AAAA. Ele facilita filtros e gráficos mensais na planilha.

Após gravar com sucesso, o bot exibe a mensagem de confirmação com o resumo do lançamento.

---

## Fluxo de Lançamento por Texto

Quando o usuário digita um texto (que não seja um comando iniciado com `/`), o bot tenta interpretar como um lançamento financeiro.

O formato esperado é: `<descrição> <valor> [categoria]`

Exemplos válidos:
- `Farmácia 45,50 Saúde`
- `Supermercado 230,00 Alimentação`
- `Salário 3500 Receita`
- `Uber 18,90` (categoria omitida, usa "Outros")

O algoritmo de parsing funciona assim:
1. Divide o texto em partes separadas por espaço
2. Percorre as partes procurando a primeira que pode ser convertida em número float (substituindo vírgula por ponto)
3. Tudo que vem antes do número é a descrição
4. Tudo que vem depois do número é a categoria
5. A categoria é validada contra a lista oficial (sem distinção de maiúsculas/minúsculas)
6. Se não corresponder a nenhuma categoria, usa "Outros"
7. A data é sempre a data de hoje, já que textos manuais geralmente representam gastos imediatos

Após o parse, o fluxo de confirmação é idêntico ao de foto, exceto que não existe a opção de editar categoria (o usuário já digitou a categoria e pode simplesmente cancelar e redigitar).

---

## Comandos Disponíveis

### /start
Exibe uma mensagem de boas-vindas explicando como usar o bot, com instruções tanto para envio de foto quanto para texto.

### /ajuda
Lista todos os comandos disponíveis com uma breve descrição de cada um. Também mostra o formato aceito para lançamentos por texto.

### /ultimo
Busca todas as linhas da planilha, ignora linhas vazias e exibe a última linha registrada com data, descrição, categoria, valor e tipo.

### /saldo
Lê todas as linhas da planilha (ignorando o cabeçalho), soma separadamente todos os valores marcados como "Receita" e todos os marcados como "Despesa", calcula o saldo líquido e exibe o resumo. Se o saldo for positivo, exibe um círculo verde; se negativo, um círculo vermelho.

---

## Sistema de Categorias

O bot usa exatamente 9 categorias fixas:

- **Alimentação** — supermercado, restaurante, delivery, padaria
- **Transporte** — combustível, Uber, ônibus, estacionamento
- **Saúde** — farmácia, consulta médica, exames, plano de saúde
- **Educação** — cursos, livros, mensalidade escolar
- **Lazer** — cinema, viagem, streaming, jogos
- **Moradia** — aluguel, condomínio, conta de luz, água, internet
- **Vestuário** — roupas, calçados, acessórios
- **Receita** — salário, freelance, Pix recebido, rendimentos
- **Outros** — tudo que não se encaixa nas categorias anteriores

A categoria "Receita" tem um comportamento especial: quando selecionada, o campo "tipo" automaticamente muda para "Receita" em vez de "Despesa". Isso permite que o comando `/saldo` calcule o balanço corretamente.

---

## Controle de Acesso

O bot tem um mecanismo opcional de lista branca de usuários. A variável de ambiente `ALLOWED_USER_IDS` aceita uma lista de IDs numéricos do Telegram separados por vírgula.

Se a lista estiver vazia, qualquer pessoa que encontrar o bot pode usá-lo. Se a lista tiver IDs, apenas esses usuários conseguem usar as funções de registrar lançamentos e ver o saldo. Usuários não autorizados recebem a mensagem "Acesso não autorizado" e nenhum dado é processado.

---

## Estrutura da Planilha Google Sheets

A planilha deve ter uma aba chamada **Lançamentos**. O bot escreve 7 colunas em cada linha:

| Coluna | Conteúdo | Exemplo |
|--------|----------|---------|
| A | Data | 28/03/2026 |
| B | Descrição | Supermercado Pão de Açúcar |
| C | Categoria | Alimentação |
| D | Valor | 187.50 |
| E | Tipo | Despesa |
| F | Mês/Ano | 03/2026 |
| G | Observação | (campo livre) |

O valor é escrito com ponto decimal para compatibilidade com fórmulas do Google Sheets. A opção `value_input_option="USER_ENTERED"` faz o Google interpretar os valores como se o usuário tivesse digitado, convertendo automaticamente datas e números para os tipos corretos.

---

## Custo de Operação

O principal custo variável é o uso do GPT-4o Vision da OpenAI. O modelo cobra por tokens de entrada (incluindo a imagem) e tokens de saída.

Uma imagem de comprovante típica, junto com o prompt e a resposta JSON, consome aproximadamente 1.000 a 1.500 tokens no total. Com o preço atual do GPT-4o (por volta de US$ 0,0025 por 1.000 tokens de entrada e US$ 0,01 por 1.000 tokens de saída), cada análise de comprovante custa entre US$ 0,001 e US$ 0,002, ou seja, menos de 1 centavo de dólar por cupom.

Para uma família que registra 30 comprovantes por mês, o custo mensal seria de aproximadamente US$ 0,06, menos de 30 centavos de reais.

O Google Sheets e a API do Telegram são gratuitos para esse volume de uso.

---

## Como Implantar e Manter Rodando

### Requisitos
- Python 3.10 ou superior
- Dependências: `pip install -r requirements.txt`
- Arquivo `.env` com as 6 variáveis obrigatórias

### Variáveis de ambiente obrigatórias
- `TELEGRAM_TOKEN` — token do bot gerado pelo @BotFather
- `OPENAI_API_KEY` — chave da API da OpenAI
- `GOOGLE_SHEETS_ID` — ID da planilha (extraído da URL)
- `GOOGLE_CLIENT_ID` — client ID do projeto no Google Cloud Console
- `GOOGLE_CLIENT_SECRET` — client secret do projeto no Google Cloud
- `GOOGLE_REFRESH_TOKEN` — refresh token OAuth2 gerado na primeira autenticação

### Variável opcional
- `ALLOWED_USER_IDS` — lista de IDs do Telegram separados por vírgula (deixar vazio para acesso livre)

### Onde rodar
O bot usa long polling, ou seja, fica em loop fazendo requisições para o Telegram perguntando se há novas mensagens. Ele precisa de um processo rodando continuamente. Opções:

- **VPS (servidor virtual privado)** — solução mais robusta, roda 24h por dia
- **Raspberry Pi** — computador de placa única barato, ótimo para uso doméstico
- **Railway ou Render** — plataformas cloud com tier gratuito suficiente para bots pessoais
- **Google Cloud Run** — paga apenas pelo tempo de processamento real

---

## Tratamento de Erros

O bot tem tratamento de erros em todos os pontos críticos:

- Se o GPT-4o não conseguir extrair os dados da imagem (foto muito escura, ângulo ruim, documento ilegível), o bot avisa o usuário e sugere enviar os dados por texto.
- Se os dados expirarem da memória temporária (reinício do bot, por exemplo) e o usuário tentar confirmar, o bot pede para enviar o comprovante novamente.
- Se ocorrer um erro ao gravar no Google Sheets (problema de autenticação, planilha não encontrada), o bot exibe a mensagem de erro para o usuário.
- Todos os erros são registrados no log com timestamp para facilitar diagnóstico.

---

## Limitações e Considerações

- **Estado em memória**: os dados pendentes ficam em `context.user_data`, que é perdido se o bot for reiniciado. O usuário precisaria enviar o comprovante novamente.
- **Uma planilha por instância**: o bot está configurado para uma planilha específica. Para múltiplos usuários com planilhas separadas, seria necessário adaptar o código.
- **Dependência de internet**: o bot requer conexão ativa para se comunicar com o Telegram, a OpenAI e o Google Sheets.
- **Reconhecimento de imagem**: imagens muito desfocadas, com baixa iluminação ou muito inclinadas podem resultar em extração incorreta. O usuário sempre pode corrigir a categoria ou cancelar e digitar manualmente.

---

## Resumo do Fluxo de Dados

```
Usuário envia foto pelo Telegram
          ↓
Bot faz download da imagem em alta resolução
          ↓
Imagem convertida para base64
          ↓
Enviada para GPT-4o Vision com prompt em português
          ↓
GPT-4o retorna JSON com: data, valor, descrição, categoria, tipo
          ↓
Bot exibe dados + botões de confirmação/edição/cancelamento
          ↓
Usuário confirma (ou edita categoria e confirma)
          ↓
Bot autentica no Google via OAuth2 (refresh token)
          ↓
Nova linha adicionada na planilha "Lançamentos"
          ↓
Confirmação enviada ao usuário no Telegram
```
