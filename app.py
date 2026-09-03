from __future__ import annotations

import os
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st
import yaml

from src.evidence_builder import (
    BuildRequest,
    build_evidence_pack,
)


def resource_path(relative_path: str) -> Path:
    base_path = Path(
        getattr(
            sys,
            "_MEIPASS",
            Path(__file__).resolve().parent,
        )
    )
    return base_path / relative_path


def executable_sector() -> str | None:
    executable_name = Path(sys.executable).stem.lower()

    executable_mapping = {
        "food_agri_esg_builder": "Food_Agri",
        "transport_logistics_esg_builder":
            "Transport_Logistics",
        "public_esg_builder": "Public",
    }

    return executable_mapping.get(executable_name)


def parse_urls(value: str) -> list[str]:
    results: list[str] = []

    for line in value.replace(",", "\n").splitlines():
        url = line.strip()

        if url:
            results.append(url)

    return list(dict.fromkeys(results))


def valid_public_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
    )


def read_file(path: Path) -> bytes:
    return path.read_bytes()


st.set_page_config(
    page_title="BB ESG Evidence Builder",
    page_icon="🌱",
    layout="wide",
)

st.title("BB Sustainability Evidence Builder")
st.caption(
    "MVP desktop application for approved public ESG evidence."
)

st.warning(
    "Use public customer information only. Do not enter or upload "
    "confidential or higher-classified customer information."
)

sector_configuration = yaml.safe_load(
    resource_path("config/sectors.yml").read_text(
        encoding="utf-8"
    )
)["sectors"]

locked_sector = executable_sector()

if locked_sector:
    selected_sector_key = locked_sector
    selected_sector = sector_configuration[
        selected_sector_key
    ]

    st.info(
        f"Sector application: "
        f"{selected_sector['display_name']}"
    )
else:
    selected_sector_key = st.selectbox(
        "Sector",
        options=list(sector_configuration.keys()),
        format_func=lambda key: sector_configuration[
            key
        ]["display_name"],
    )

    selected_sector = sector_configuration[
        selected_sector_key
    ]

with st.form("evidence_intake_form"):
    left, right = st.columns(2)

    with left:
        customer_name = st.text_input(
            "Customer name *",
            placeholder="Example Company B.V.",
        )

        official_website = st.text_input(
            "Official customer website *",
            placeholder="https://www.example.com",
        )
        
        default_ing_guidance_url = (
        selected_sector.get(
        "ing_sector_guidance_url",
        "",)
        )

        ing_sector_guidance_url = st.text_input(
            "ING public sector-guidance website *",
            value=default_ing_guidance_url,
            help=(
                "This must be the approved ING public sector page "
                "for the selected sector."
            ),
        )
        approved_urls_text = st.text_area(
            "Additional approved public URLs",
            placeholder=(
                "https://www.example.com/sustainability\n"
                "https://reports.example.com/esg-report.pdf"
            ),
            help=(
                "Enter one approved URL per line. Add investor "
                "relations or PDF-hosting domains when different "
                "from the main website."
            ),
        )

        country = st.text_input(
            "Country",
            placeholder="Netherlands",
        )

        language = st.selectbox(
            "Preferred output language",
            ["English"],
        )

    with right:
        servicing_model = st.text_input(
            "Servicing model",
            placeholder="Business Banking",
        )

        rm_name = st.text_input("RM name *")

        rm_email = st.text_input("RM email *")

        uploaded_pdfs = st.file_uploader(
            "Optional public ESG or annual-report PDFs",
            type=["pdf"],
            accept_multiple_files=True,
            help=(
                "Upload public reports only. Do not upload "
                "confidential customer files to this MVP."
            ),
        )

        output_location = st.text_input(
            "Suggested SharePoint output folder",
            value=(
                "/BB Sustainability Pitch Builder/"
                "01_Public_Evidence_Packs/"
                f"{selected_sector['folder_name']}/"
            ),
            disabled=True,
        )

    public_confirmation = st.checkbox(
        (
            "I confirm that all entered URLs and uploaded files "
            "are approved public sources and contain no prohibited "
            "confidential information."
        )
    )

    submitted = st.form_submit_button(
        "Build ESG evidence pack",
        type="primary",
    )

if submitted:
    validation_errors: list[str] = []

    if not customer_name.strip():
        validation_errors.append("Customer name is required.")

    if not official_website.strip():
        validation_errors.append(
            "Official customer website is required."
        )
    elif not valid_public_url(official_website.strip()):
        validation_errors.append(
            "Official website must be a valid HTTP or HTTPS URL."
        )
        
    if not ing_sector_guidance_url.strip():
        validation_errors.append(
        "ING public sector-guidance website is required."
    )
    elif not valid_public_url(
        ing_sector_guidance_url.strip()
        ):
        validation_errors.append(
        "ING sector-guidance website must be a valid URL."
        )
    else:
        ing_hostname = (
            urlparse(
                ing_sector_guidance_url.strip()
            ).hostname
            or ""
        ).lower()
    
        if not (
            ing_hostname == "ing.nl"
            or ing_hostname.endswith(".ing.nl")
        ):
            validation_errors.append(
                "ING sector-guidance website must use "
                "an approved ing.nl domain."
            )

    approved_urls = parse_urls(approved_urls_text)

    invalid_urls = [
        url
        for url in approved_urls
        if not valid_public_url(url)
    ]

    if invalid_urls:
        validation_errors.append(
            "These additional URLs are invalid: "
            + ", ".join(invalid_urls)
        )

    if not rm_name.strip():
        validation_errors.append("RM name is required.")

    if not rm_email.strip() or "@" not in rm_email:
        validation_errors.append(
            "A valid RM email address is required."
        )

    if not public_confirmation:
        validation_errors.append(
            "Public-source confirmation is required."
        )

    if validation_errors:
        for error in validation_errors:
            st.error(error)
    else:
        request_id = (
            "ESG-"
            + datetime.now().strftime("%Y%m%d-%H%M%S")
            + "-"
            + uuid.uuid4().hex[:6].upper()
        )

        request = BuildRequest(
        customer_name=customer_name.strip(),
        sector=selected_sector_key,
        website=official_website.strip(),
        approved_source_urls=approved_urls,
        ing_sector_guidance_url=(
            ing_sector_guidance_url.strip()
        ),
        servicing_model=servicing_model.strip(),
        country=country.strip(),
        language=language,
        rm_name=rm_name.strip(),
        rm_email=rm_email.strip(),
        request_id=request_id,)

        uploaded_pdf_content = [
            (uploaded.name, uploaded.getvalue())
            for uploaded in uploaded_pdfs
        ]

        temporary_root = Path(
            tempfile.mkdtemp(prefix="bb_esg_")
        )

        output_directory = (
            temporary_root
            / selected_sector["folder_name"]
            / request_id
        )

        try:
            with st.status(
                "Building ESG evidence pack...",
                expanded=True,
            ) as build_status:
                st.write("Collecting customer public website evidence")
                st.write("Extracting customer PDF text and tables")
                st.write("Collecting ING public sector guidance")
                st.write("Excluding podcast and audio content")
                st.write("Mapping customer evidence to ING sector topics")
                st.write("Creating Excel and Markdown artifacts")

                artifacts = build_evidence_pack(
                    request=request,
                    sector_config=selected_sector,
                    sector_source_file=resource_path(
                        "reference/sector_kpis_data_sources.csv"
                    ),
                    output_directory=output_directory,
                    uploaded_pdfs=uploaded_pdf_content,
                    )

                st.session_state["last_artifacts"] = {
                    key: str(path)
                    for key, path in artifacts.items()
                }
                st.session_state["last_request_id"] = (
                    request_id
                )
                st.session_state["last_customer"] = (
                    customer_name
                )
                st.session_state["last_sector"] = (
                    selected_sector["display_name"]
                )

                build_status.update(
                    label="Evidence pack ready",
                    state="complete",
                    expanded=False,
                )

        except Exception as exc:
            st.error(
                "The evidence build failed. "
                f"Technical detail: {exc}"
            )

if "last_artifacts" in st.session_state:
    artifacts = {
        key: Path(value)
        for key, value
        in st.session_state["last_artifacts"].items()
    }

    st.success(
        f"Request {st.session_state['last_request_id']} "
        "is ready."
    )

    st.subheader("Download evidence artifacts")

    first, second, third = st.columns(3)

    with first:
        st.download_button(
            "Download complete ZIP",
            data=read_file(artifacts["zip"]),
            file_name=artifacts["zip"].name,
            mime="application/zip",
            type="primary",
        )

    with second:
        st.download_button(
            "Download Excel workbook",
            data=read_file(artifacts["excel"]),
            file_name=artifacts["excel"].name,
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )

    with third:
        st.download_button(
            "Download Markdown evidence",
            data=read_file(artifacts["markdown"]),
            file_name=artifacts["markdown"].name,
            mime="text/markdown",
        )

    st.subheader("Next steps")

    st.markdown(
    f"""
    1. Download and extract `{artifacts["zip"].name}`.
    2. Upload `ESG_data_<customer>.xlsx` to the approved SharePoint folder.
    3. Upload `ESG_evidence_<customer>.md` to the same folder.
    4. Upload permitted public PDFs where required.
    5. Wait for SharePoint indexing.
    6. Run the `{selected_sector["display_name"]}` Agent 1.
    7. Provide Agent 1 with the customer name, Request ID and evidence-folder link.
    8. Save Agent 1 output in its approved SharePoint folder.
    9. Run Agent 2 using only the saved Agent 1 output.
    """
    )

with st.sidebar:
    st.header("Application information")
    st.write(
        "This application runs locally and writes no data "
        "directly to SharePoint."
    )

    st.write(
        "Close the browser tab and select Exit application "
        "when finished."
    )

    if st.button("Exit application"):
        st.warning("The local application is closing.")
        os._exit(0)