from pypdf import PdfReader


class IngestionService:
    def extract_text(self, file_path):
        reader = PdfReader(file_path)
        text = ""

        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"

        return text