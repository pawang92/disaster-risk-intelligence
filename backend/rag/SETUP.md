# Local RAG setup — Windows Command Prompt

These steps use **Command Prompt (`cmd.exe`)**, not PowerShell. The pipeline stores vectors locally in the free Chroma database at `.chroma\`; no cloud vector database or AWS infrastructure deployment is needed.

## Before you start

Install Python 3.11 or newer and AWS CLI v2. You also need an AWS account with access to the Bedrock embedding and chat models selected in `.env.local`.

Open **Command Prompt** and configure an AWS profile once. Replace `disaster-rag` with your own profile name if needed.

```cmd
aws configure --profile disaster-rag
set AWS_PROFILE=disaster-rag
aws sts get-caller-identity
```

The last command must show your AWS account ID. Your IAM user or role requires `bedrock:InvokeModel` permission for both configured models. Do not save AWS access keys in this repository or in `.env.local`.

## 1. Create the Python environment

Run these commands from Command Prompt:

```cmd
cd /d D:\python_projects\disaster-risk-intelligence\backend\rag
py -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env.local
```

`cd /d` changes both the drive and directory. Every new Command Prompt window needs `.venv\Scripts\activate.bat` again.

## 2. Check `.env.local`

Open `D:\python_projects\disaster-risk-intelligence\backend\rag\.env.local` in an editor. Keep the Chroma values as shown. Change `BEDROCK_CHAT_MODEL_ID` only if you enabled a different model in Bedrock.

```dotenv
AWS_REGION=ap-south-1
CHROMA_COLLECTION=disaster-guidance
CHROMA_PATH=./.chroma
BEDROCK_EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0
BEDROCK_CHAT_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0
EMBEDDING_MIN_INTERVAL_SECONDS=8
EMBEDDING_MAX_ATTEMPTS=8
DEBUG=true
```

For `AWS_REGION=ap-south-1`, this guide uses `anthropic.claude-3-haiku-20240307-v1:0`. In the AWS Console, open **Amazon Bedrock → Model catalog**, open Claude 3 Haiku, and complete the model-access request if your account has not enabled it yet.

### Free local answers with Ollama

The document vectors already use local E5 embeddings. To avoid Bedrock answer-generation quotas and costs too, install [Ollama for Windows](https://ollama.com/download), then run this once in Command Prompt:

```cmd
ollama pull gemma3:4b
```

Set these values in `.env.local` and restart the API:

```dotenv
ANSWER_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=gemma3:4b
```

`ANSWER_PROVIDER=ollama` never calls Bedrock to generate answers. Use `ANSWER_PROVIDER=auto` if you prefer Bedrock normally but want Ollama to handle throttling or quota errors. Ollama needs the model downloaded locally and enough RAM; no per-request cloud fee applies.

### If Bedrock embeddings are throttled

Use the free local multilingual embedding model instead. In `.env.local`, change the embedding settings to:

```dotenv
EMBEDDING_PROVIDER=local
LOCAL_EMBEDDING_MODEL=intfloat/multilingual-e5-base
```

Run `pip install -r requirements.txt` again. On the first ingestion, the model downloads once (roughly 1 GB) and is then cached on your machine. Re-ingest every PDF after changing providers because the local and Bedrock embedding vectors are different. The application keeps them in separate Chroma collections so they cannot be mixed. Bedrock is still used only to generate the final natural-language answer.

Before ingesting, confirm the local provider is active. The command must print `Embedding provider: local`:

```cmd
python -m app.ingest "C:\path\to\flood-guidance-marathi.pdf" --district mumbai --disaster-type flood --ocr --dry-run
```

`--dry-run` extracts the PDF and reports its chunk count without embedding or storing anything. It is safe to run with a large PDF. Remove `--dry-run` only after the provider line shows `local`.

## 3. Ingest a PDF

In the same activated Command Prompt, set the profile and configuration file, then replace the PDF path with your own path:

```cmd
set AWS_PROFILE=disaster-rag
set ENV_FILE=D:\python_projects\disaster-risk-intelligence\backend\rag\.env.local
python -m app.ingest "C:\path\to\flood-guidance-marathi.pdf" --district pune --disaster-type flood --ocr
```

Use `--ocr` for scanned PDFs. For PDFs where text can be selected and copied, omit `--ocr` for faster ingestion. The command creates/updates `backend\rag\.chroma\`.

Large PDFs are supported. The ingestion process embeds one chunk at a time and intentionally pauses for eight seconds between requests to stay within conservative Bedrock limits. Do not start a second ingestion while one is running. If Bedrock still prints a throttling message, leave the command running: it retries with an increasing delay. Check **AWS Console → Service Quotas → Amazon Bedrock** for the request-per-minute and token-per-minute quota of your embedding model before reducing `EMBEDDING_MIN_INTERVAL_SECONDS`.

## 4. Start the API

Use the same Command Prompt after ingestion:

```cmd
set AWS_PROFILE=disaster-rag
set ENV_FILE=D:\python_projects\disaster-risk-intelligence\backend\rag\.env.local
uvicorn app.main:app --reload --port 8080
```

Keep this window open. Open [http://127.0.0.1:8080/docs](http://127.0.0.1:8080/docs) in your browser and use `POST /v1/ask` to ask English or Marathi questions.

## 5. Test from a second Command Prompt

Open a second `cmd.exe` window and run:

```cmd
cd /d D:\python_projects\disaster-risk-intelligence\backend\rag
.venv\Scripts\activate.bat
curl.exe -X POST http://127.0.0.1:8080/v1/ask -H "Content-Type: application/json" -d "{\"question\":\"पूर येण्यापूर्वी कोणती तयारी करावी?\",\"language\":\"mr\",\"district\":\"pune\",\"disaster_type\":\"flood\"}"
```

The `.chroma\` folder is ignored by Git and persists across restarts. Delete it only when you deliberately want to erase the locally indexed documents.
