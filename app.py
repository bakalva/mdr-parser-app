import io
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from universal_mdr_parser_v2 import process_file

st.set_page_config(page_title="MDR Report Generator", layout="wide")

st.title("MDR Report Generator")
st.write("Загрузи файл Stripe или Unlimit и скачай готовый отчет.")

domestic_country = st.text_input(
    "Domestic country for Stripe region mapping",
    value="GB"
).strip().upper()

uploaded_file = st.file_uploader(
    "Upload Excel or CSV file",
    type=["xlsx", "xls", "csv"]
)

if uploaded_file is not None:
    suffix = Path(uploaded_file.name).suffix or ".xlsx"

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.getbuffer())
        temp_input_path = Path(tmp.name)

    try:
        result = process_file(temp_input_path, domestic_country=domestic_country)

        st.success("Report created successfully.")
        st.dataframe(result, use_container_width=True)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            result.to_excel(writer, index=False, sheet_name="report")

        output.seek(0)

        st.download_button(
            label="Download result.xlsx",
            data=output,
            file_name="result.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        st.error(f"Error: {e}")

    finally:
        try:
            temp_input_path.unlink(missing_ok=True)
        except Exception:
            pass
