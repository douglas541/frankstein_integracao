import re
import pdfplumber
import os

class PDFCleaner:
    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        self.pages = []

    def load_pdf(self):
        with pdfplumber.open(self.pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    self.pages.append(PageContent(text))

    def clean_pages(self):
        cleaned_pages = []
        for page in self.pages:
            # Limpa o conteúdo da página removendo quebras de linha e caracteres especiais
            page.page_content = page.page_content.replace("\n", " ")
            page.page_content = ' '.join(page.page_content.split())  # Remove espaços extras
            page.page_content = re.sub(r'\s*\.\s*\.\s*', ' ', page.page_content)  # Remove trechos com "..."
            page.page_content = re.sub(r"[^\w\s]", " ", page.page_content)        # Remove pontuações, exceto palavras e espaços
            page.page_content = re.sub(r"\s+", " ", page.page_content)           # Remove espaços múltiplos

            if page.page_content.strip():
                cleaned_pages.append(page)

        self.pages = cleaned_pages

    def save_to_txt(self, output_txt_path):
        with open(output_txt_path, "w", encoding="utf-8") as file:
            for page in self.pages:
                file.write(page.page_content + "\n")  # Adiciona quebra de linha entre páginas

class PageContent:
    def __init__(self, content):
        self.page_content = content

def process_all_pdfs_in_directory(directory):
    # Itera por todos os arquivos no diretório
    for filename in os.listdir(directory):
        if filename.endswith(".pdf"):  # Verifica se o arquivo é um PDF
            pdf_path = os.path.join(directory, filename)
            txt_output_path = os.path.join(directory, filename.replace(".pdf", "_cleaned.txt"))
            
            print(f"Processando {filename}...")

            # Processa o PDF e limpa o conteúdo
            cleaner = PDFCleaner(pdf_path)
            cleaner.load_pdf()
            cleaner.clean_pages()
            cleaner.save_to_txt(txt_output_path)

            print(f"Salvo: {txt_output_path}")

if __name__ == "__main__":
    directory = "manuais"  # Diretório onde estão os manuais
    process_all_pdfs_in_directory(directory)
    print("Processamento de todos os PDFs concluído.")
