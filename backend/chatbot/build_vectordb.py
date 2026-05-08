from pathlib import Path
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

BASE_DIR   = Path(__file__).parent                 
KB_PATH = BASE_DIR / "Knowledge Base.pdf"
CHROMA_DIR = str(BASE_DIR / "chroma_db")         


CHUNK_SIZE    = 800
CHUNK_OVERLAP = 120


EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def build():
    print("=" * 60)
    print("  PneumaVision — Knowledge Base Vector DB Builder")
    print("=" * 60)

    print(f"\n[1/4] Loading knowledge base from: {KB_PATH.name}")
    if not KB_PATH.exists():
        raise FileNotFoundError(
            f"knowledge_base.txt not found at {KB_PATH}\n"
            "Make sure it is in the same folder as this script."
        )
    loader = PyPDFLoader(str(KB_PATH))
    documents = loader.load()
    print(f"  Loaded {len(documents)} document(s), "
          f"{sum(len(d.page_content) for d in documents):,} characters total")

    print(f"\n[2/4] Splitting into chunks "
          f"(size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP})...")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        # Try to split at these boundaries in order — keeps sections intact
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(documents)
    print(f"  Created {len(chunks)} chunks")

    # Quick preview of first chunk
    print(f"\n  Preview of chunk #1:")
    print(f"  {'-'*50}")
    print(f"  {chunks[0].page_content[:200]}...")
    print(f"  {'-'*50}")

    print(f"\n[3/4] Loading embedding model: {EMBED_MODEL}")
    print("  (This may take a moment on first run — model will be cached)")
    embeddings = HuggingFaceEmbeddings(
        model_name=EMBED_MODEL,
        model_kwargs={"device": "cpu"},   
        encode_kwargs={"normalize_embeddings": True},
    )
    print("  Embedding model ready")

    print(f"\n[4/4] Embedding {len(chunks)} chunks and saving to: {CHROMA_DIR}")
    print("  (This is the slow step — only runs once)")

    vectordb = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=CHROMA_DIR,
        collection_name="pneumavision_kb",
    )

    print(f"\n{'='*60}")
    print(f"  ✅ Vector DB built successfully!")
    print(f"  📁 Saved to: {CHROMA_DIR}")
    print(f"  📦 Total chunks stored: {vectordb._collection.count()}")
    print(f"{'='*60}")
    print("\n  You can now start the FastAPI server.")
    print("  The RAG chain will load this DB automatically — no rebuild needed.\n")


if __name__ == "__main__":
    build()