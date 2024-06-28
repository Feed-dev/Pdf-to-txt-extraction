import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import os
import spacy
from pinecone import Pinecone, ServerlessSpec
from langchain_cohere import CohereEmbeddings
from dotenv import load_dotenv
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

# Keys
PINECONE_API_KEY = os.environ["PINECONE_API_KEY"]
PINECONE_ENVIRONMENT = os.environ["PINECONE_ENVIRONMENT"]
PINECONE_INDEX_NAME = os.environ["PINECONE_INDEX_NAME2"]

# Configure pytesseract path to the Tesseract executable
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# Load spaCy English model
nlp = spacy.load("en_core_web_sm")

# Initialize Cohere embeddings
embeddings = CohereEmbeddings(model="embed-multilingual-v3.0")

# Pinecone initialization
pc = Pinecone(api_key=PINECONE_API_KEY)

def create_pinecone_index(index_name, dimension=1024):
    if index_name not in pc.list_indexes().names():
        pc.create_index(
            name=index_name,
            dimension=dimension,
            metric='cosine',
            metadata_config={'indexed': ['file', 'page', 'map', 'alignment', 'goal', 'purpose', 'tradition', 'practices']},
            spec=ServerlessSpec(cloud='aws', region='us-east-1')
        )
    return pc.Index(index_name)

def extract_text_from_page(page):
    try:
        text = page.get_text()
        if text.strip():  # If there's text, it's not a scan
            return text
        else:  # If no text, it's likely a scan
            pix = page.get_pixmap()
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            text = pytesseract.image_to_string(img)
            return text
    except Exception as e:
        logger.error(f"Error extracting text from page: {e}")
        return ""

def preprocess_text(text):
    doc = nlp(text)
    cleaned_text = [token.lemma_.lower() for token in doc if not token.is_stop and not token.is_punct and not token.is_space]
    return ' '.join(cleaned_text)

def chunk_text(text, chunk_size=500):
    words = text.split()
    return [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]

def vectorize_text(text_chunks, file_name, page_num, metadata):
    return [
        (f"{file_name}_page_{page_num}_chunk_{i}", 
         embeddings.embed_query(chunk), 
         {
            "text": chunk,  # Store the actual text
            "file": file_name,
            "page": page_num,
            **metadata  # Include all other metadata
         })
        for i, chunk in enumerate(text_chunks)
    ]

def batch_upload_vectors(index, vector_data, namespace, batch_size=100):
    for i in range(0, len(vector_data), batch_size):
        batch = vector_data[i:i + batch_size]
        upserts = [
            {
                "id": item[0],
                "values": item[1],
                "metadata": item[2]
            }
            for item in batch
        ]
        index.upsert(vectors=upserts, namespace=namespace)

def process_pdf(file_path, index, namespace, metadata):
    try:
        file_name = os.path.splitext(os.path.basename(file_path))[0]
        doc = fitz.open(file_path)
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            page_text = extract_text_from_page(page)
            if not page_text.strip():
                logger.warning(f"No text extracted from page {page_num} of {file_path}")
                continue
            processed_text = preprocess_text(page_text)
            chunks = chunk_text(processed_text)
            vectors = vectorize_text(chunks, file_name, page_num, metadata)
            batch_upload_vectors(index, vectors, namespace)
        doc.close()
        logger.info(f"Successfully processed {file_path}")
    except fitz.FileDataError as e:
        logger.error(f"Failed to open file {file_path}: {e}")
    except Exception as e:
        logger.error(f"Error processing file {file_path}: {e}")

def main(pdf_directory, index_name, namespace, metadata):
    index = create_pinecone_index(index_name)
    for root, dirs, files in os.walk(pdf_directory):
        for file in files:
            if file.endswith('.pdf'):
                file_path = os.path.join(root, file)
                logger.info(f"Processing: {file_path}")
                process_pdf(file_path, index, namespace, metadata)

if __name__ == "__main__":
    # Example usage for a small test index
    test_pdf_directory = r'F:\e-boeken\the-mystic-library\Mystic_Library_A_Z\Astral Workings'
    test_index_name = PINECONE_INDEX_NAME
    test_namespace = "astral workings"
    test_metadata = {
        "map": "astral-workings",
        "alignment": "spiritual development",
        "goal": "explore inner self",
        "purpose": "astral projection",
        "tradition": "esoteric",
        "practices": "meditation, visualization"
    }
    main(test_pdf_directory, test_index_name, test_namespace, test_metadata)
