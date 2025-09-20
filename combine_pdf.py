import fitz

def combine_pdfs(pdf_list, output="combined.pdf"):
    """
    Combines multiple PDF files into a single PDF.

    Args:
        pdf_list (list): A list of file paths to the PDF documents to be merged.
        output (str): The name of the output merged PDF file.
    """

    output_pdf = fitz.open()  # Create a new empty PDF for output

    for pdf_file in pdf_list:
        try:
            # source_pdf = fitz.open() # 通常のファイルのとき
            source_pdf = fitz.open(stream = pdf_file.read(), filetype = "pdf") # streamlit用
            output_pdf.insert_pdf(source_pdf)
            source_pdf.close()
        except fitz.FileNotFoundError:
            print(f"Error: PDF file not found: {pdf_file}")
        except Exception as e:
            print(f"An error occurred while processing {pdf_file}: {e}")

    output_pdf.save(output)
    output_pdf.close()
    print(f"PDFs successfully merged into {output}")

if __name__ == "__main__":
    # Create some dummy PDF files for demonstration
    # In a real scenario, these would be existing PDF files
    with open("doc1.pdf", "wb") as f:
        f.write(fitz.open().new_page().write_text("This is document 1").tobytes())
    with open("doc2.pdf", "wb") as f:
        f.write(fitz.open().new_page().write_text("This is document 2").tobytes())

    pdf_files_to_merge = ["02_bar.pdf", "99_back.pdf", "00_cover.pdf", "01_foo.pdf"]
    combine_pdfs(pdf_files_to_merge, "combined_output.pdf")
