from __future__ import annotations

import hashlib
import io
import ipaddress
import json
import re
import socket
import zipfile
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import pandas as pd
import pdfplumber
import pymupdf
import requests
from bs4 import BeautifulSoup


YEAR_PATTERN = re.compile(r"\b(19\d{2}|20\d{2})\b")

#VALUE_PATTERN = re.compile(
#    r"""
#    (?P<value>
#        -?
#        \d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?
#        |
#        -?\d+(?:\.\d+)?
#    )
#    \s*
#    (?P<unit>
#        %|
#        tCO2e|
#        ktCO2e|
#        MtCO2e|
#        tonnes?\s+CO2e|
#        metric\s+tons?\s+CO2e|
#        MWh|
#        GWh|
#        kWh|
#        GJ|
#        m3|
#        megalitres?|
#        tonnes?|
#        metric\s+tons?|
#        kilograms?|
#        kg|
#        employees?|
#        FTE
#    )?
#    """,
#    re.IGNORECASE | re.VERBOSE,
##)

@dataclass
class BuildRequest:
    customer_name: str
    sector: str
    website: str
    approved_source_urls: list[str]
    ing_sector_guidance_url: str
    servicing_model: str
    country: str
    language: str
    rm_name: str
    rm_email: str
    request_id: str


@dataclass
class BuildSettings:
    max_sources: int = 30
    max_crawl_depth: int = 1
    timeout_seconds: int = 30
    max_download_bytes: int = 50 * 1024 * 1024
    max_text_characters_per_source: int = 250_000
    user_agent: str = "ING-BB-ESG-Evidence-Builder-MVP/1.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_name(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return result.strip("_") or "unknown"

def load_sector_reference(
    source_file: Path,
    sector: str,
) -> pd.DataFrame:
    """
    Load approved sector source guidance for the selected sector.

    This file is a source catalogue, not a quantitative KPI taxonomy.
    It must not be used to claim that a company follows, meets, leads,
    or underperforms a sector pathway.
    """
    if not source_file.exists():
        raise FileNotFoundError(
            f"Sector source catalogue was not found: {source_file}"
        )

    reference = pd.read_csv(source_file).fillna("")

    required_columns = {
        "Sector",
        "Display_Name",
        "KPIs_Data_Sources",
    }

    missing_columns = required_columns.difference(
        reference.columns
    )

    if missing_columns:
        raise ValueError(
            "Sector source catalogue is missing columns: "
            + ", ".join(sorted(missing_columns))
        )

    selected = reference[
        reference["Sector"].astype(str).str.strip() == sector
    ].copy()

    if selected.empty:
        raise ValueError(
            f"No sector source guidance exists for sector: {sector}"
        )

    return selected

def validate_public_hostname(hostname: str) -> None:
    try:
        records = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(
            f"Cannot resolve hostname: {hostname}"
        ) from exc

    for record in records:
        address = ipaddress.ip_address(record[4][0])

        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise ValueError(
                f"URL does not resolve to a public address: {hostname}"
            )


def validate_url(url: str, allowed_hosts: set[str]) -> None:
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported URL scheme: {url}")

    if not parsed.hostname:
        raise ValueError(f"URL has no hostname: {url}")

    hostname = parsed.hostname.lower()

    if hostname not in allowed_hosts:
        raise ValueError(
            f"URL hostname is not approved for this run: {hostname}"
        )

    validate_public_hostname(hostname)


def robots_allows(
    session: requests.Session,
    url: str,
    settings: BuildSettings,
) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    parser = RobotFileParser()
    parser.set_url(robots_url)

    try:
        response = session.get(
            robots_url,
            timeout=settings.timeout_seconds,
            headers={"User-Agent": settings.user_agent},
        )

        if response.status_code == 200:
            parser.parse(response.text.splitlines())
            return parser.can_fetch(settings.user_agent, url)

        return True
    except requests.RequestException:
        return True


def read_limited_response(
    response: requests.Response,
    maximum_bytes: int,
) -> bytes:
    result = bytearray()

    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue

        result.extend(chunk)

        if len(result) > maximum_bytes:
            raise ValueError(
                f"Source is larger than the permitted "
                f"{maximum_bytes} bytes."
            )

    return bytes(result)


def fetch_url(
    session: requests.Session,
    url: str,
    allowed_hosts: set[str],
    settings: BuildSettings,
) -> tuple[bytes, str, str]:
    validate_url(url, allowed_hosts)

    if not robots_allows(session, url, settings):
        raise PermissionError(
            f"robots.txt does not permit retrieval: {url}"
        )

    response = session.get(
        url,
        timeout=settings.timeout_seconds,
        stream=True,
        allow_redirects=True,
        headers={
            "User-Agent": settings.user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/pdf;q=0.9,*/*;q=0.5"
            ),
        },
    )
    response.raise_for_status()

    final_url = response.url
    validate_url(final_url, allowed_hosts)

    content = read_limited_response(
        response,
        settings.max_download_bytes,
    )

    content_type = (
        response.headers.get("Content-Type", "")
        .split(";")[0]
        .strip()
        .lower()
    )

    return content, content_type, final_url


def extract_html(
    content: bytes,
    source_url: str,
    maximum_characters: int,
) -> tuple[str, str, list[str], list[str]]:
    soup = BeautifulSoup(content, "html.parser")

    for element in soup(
        ["script", "style", "noscript", "svg", "nav", "footer"]
    ):
        element.decompose()

    title = (
        soup.title.get_text(" ", strip=True)
        if soup.title
        else source_url
    )

    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text[:maximum_characters]

    tables: list[str] = []

    for table_number, table in enumerate(
        soup.find_all("table"),
        start=1,
    ):
        rows: list[str] = []

        for row in table.find_all("tr"):
            cells = [
                cell.get_text(" ", strip=True)
                for cell in row.find_all(["th", "td"])
            ]

            if cells:
                rows.append(" | ".join(cells))

        if rows:
            tables.append(
                f"HTML table {table_number}\n"
                + "\n".join(rows)
            )

    links = [
        urljoin(source_url, anchor["href"])
        for anchor in soup.find_all("a", href=True)
    ]

    return title, text, tables, links


def extract_pdf(
    content: bytes,
    maximum_characters: int,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    page_records: list[dict[str, Any]] = []
    table_records: list[dict[str, Any]] = []

    document = pymupdf.open(stream=content, filetype="pdf")
    metadata = document.metadata or {}
    title = metadata.get("title") or "PDF document"

    extracted_characters = 0

    for page_number, page in enumerate(document, start=1):
        if extracted_characters >= maximum_characters:
            break

        page_text = page.get_text("text", sort=True).strip()

        remaining = maximum_characters - extracted_characters
        page_text = page_text[:remaining]
        extracted_characters += len(page_text)

        page_records.append(
            {
                "page": page_number,
                "text": page_text,
            }
        )

    document.close()

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            try:
                tables = page.extract_tables()
            except Exception:
                tables = []

            for table_number, table in enumerate(tables, start=1):
                rows: list[str] = []

                for row in table or []:
                    cells = [
                        str(cell).strip()
                        if cell is not None
                        else ""
                        for cell in row
                    ]

                    if any(cells):
                        rows.append(" | ".join(cells))

                if rows:
                    table_records.append(
                        {
                            "page": page_number,
                            "table_number": table_number,
                            "text": "\n".join(rows),
                        }
                    )

    return title, page_records, table_records


def relevant_link(url: str, keywords: list[str]) -> bool:
    normalized = url.lower().replace("_", " ").replace("-", " ")

    if normalized.endswith(".pdf"):
        return True

    return any(
        keyword.lower() in normalized
        for keyword in keywords
    )


def contains_excluded_content(
    url: str,
    title: str,
    excluded_keywords: list[str],
) -> bool:
    """
    Exclude podcasts and other disallowed content using URL and title.

    Page body text is not checked because a normal article may contain
    a harmless navigation link or reference to a podcast.
    """
    searchable = f"{url} {title}".lower()

    return any(
        keyword.lower() in searchable
        for keyword in excluded_keywords
    )


def is_allowed_ing_child_url(
    root_url: str,
    candidate_url: str,
    excluded_keywords: list[str],
) -> bool:
    root = urlparse(root_url)
    candidate = urlparse(candidate_url)

    if candidate.scheme not in {"http", "https"}:
        return False

    if candidate.hostname != root.hostname:
        return False

    root_path = root.path.rstrip("/")

    if not candidate.path.startswith(root_path):
        return False

    if contains_excluded_content(
        candidate_url,
        "",
        excluded_keywords,
    ):
        return False

    return True

def add_source(
    source_records: list[dict[str, Any]],
    evidence_records: list[dict[str, Any]],
    source_url: str,
    title: str,
    source_type: str,
    source_group: str,
    content_type: str,
    content: bytes,
    text_records: list[dict[str, Any]],
    table_records: list[dict[str, Any]],
) -> str:
    """
    Add a source and its extracted evidence.

    Source groups:
    Customer_Public
    Customer_Public_Upload
    ING_Public_Sector_Guidance
    """
    source_id = f"S{len(source_records) + 1:04d}"

    source_records.append(
        {
            "Source_ID": source_id,
            "Source_Group": source_group,
            "Title": title,
            "Source_URL": source_url,
            "Source_Type": source_type,
            "Content_Type": content_type,
            "Retrieved_UTC": utc_now(),
            "SHA256": hashlib.sha256(content).hexdigest(),
            "Status": "Extracted",
        }
    )

    for item in text_records:
        evidence_records.append(
            {
                "Evidence_ID": (
                    f"E{len(evidence_records) + 1:05d}"
                ),
                "Source_ID": source_id,
                "Source_Group": source_group,
                "Source_URL": source_url,
                "Page": item.get("page", ""),
                "Evidence_Type": item.get(
                    "evidence_type",
                    f"{source_type}_TEXT",
                ),
                "Section": item.get("section", ""),
                "Evidence_Text": item.get("text", ""),
            }
        )

    for item in table_records:
        evidence_records.append(
            {
                "Evidence_ID": (
                    f"E{len(evidence_records) + 1:05d}"
                ),
                "Source_ID": source_id,
                "Source_Group": source_group,
                "Source_URL": source_url,
                "Page": item.get("page", ""),
                "Evidence_Type": f"{source_type}_TABLE",
                "Section": (
                    f"Table {item.get('table_number', '')}"
                ),
                "Evidence_Text": item.get("text", ""),
            }
        )

    return source_id


def collect_web_sources(
    request: BuildRequest,
    keywords: list[str],
    settings: BuildSettings,
    raw_directory: Path,
    extracted_directory: Path,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    seed_urls = list(
        dict.fromkeys(
            [request.website, *request.approved_source_urls]
        )
    )

    allowed_hosts = {
        parsed.hostname.lower()
        for parsed in map(urlparse, seed_urls)
        if parsed.hostname
    }

    queue = deque((url, 0) for url in seed_urls)
    visited: set[str] = set()

    source_records: list[dict[str, Any]] = []
    evidence_records: list[dict[str, Any]] = []
    error_records: list[dict[str, Any]] = []

    session = requests.Session()

    while queue and len(visited) < settings.max_sources:
        url, depth = queue.popleft()
        normalized_url = url.split("#")[0]

        if normalized_url in visited:
            continue

        visited.add(normalized_url)

        try:
            content, content_type, final_url = fetch_url(
                session,
                normalized_url,
                allowed_hosts,
                settings,
            )

            is_pdf = (
                content_type == "application/pdf"
                or final_url.lower().split("?")[0].endswith(".pdf")
                or content.startswith(b"%PDF")
            )

            if is_pdf:
                title, pages, tables = extract_pdf(
                    content,
                    settings.max_text_characters_per_source,
                )
                source_id = add_source(
                    source_records=source_records,
                    evidence_records=evidence_records,
                    source_url=final_url,
                    title=title,
                    source_type="PDF",
                    source_group="Customer_Public",
                    content_type=content_type,
                    content=content,
                    text_records=pages,
                    table_records=tables,
                )

                pdf_name = (
                    f"{source_id}_"
                    f"{safe_name(Path(urlparse(final_url).path).name)}"
                )

                if not pdf_name.lower().endswith(".pdf"):
                    pdf_name += ".pdf"

                (raw_directory / pdf_name).write_bytes(content)

                extracted_text = "\n\n".join(
                    f"Page {page['page']}\n{page['text']}"
                    for page in pages
                )

                (
                    extracted_directory / f"{source_id}.txt"
                ).write_text(
                    extracted_text,
                    encoding="utf-8",
                )

            elif content_type in {
                "text/html",
                "application/xhtml+xml",
                "",
            }:
                title, text, tables, links = extract_html(
                    content,
                    final_url,
                    settings.max_text_characters_per_source,
                )

                text_records = [
                    {
                        "page": "",
                        "section": "Web page",
                        "text": text,
                        "evidence_type": "HTML_TEXT",
                    }
                ]

                table_records = [
                    {
                        "page": "",
                        "table_number": table_number,
                        "text": table_text,
                    }
                    for table_number, table_text in enumerate(
                        tables,
                        start=1,
                    )
                ]

                source_id = add_source(
                source_records=source_records,
                evidence_records=evidence_records,
                source_url=final_url,
                title=title,
                source_type="HTML",
                source_group="Customer_Public",
                content_type=content_type,
                content=content,
                text_records=text_records,
                table_records=table_records,
         )

                (
                    extracted_directory / f"{source_id}.txt"
                ).write_text(
                    text,
                    encoding="utf-8",
                )

                if depth < settings.max_crawl_depth:
                    for link in links:
                        parsed_link = urlparse(link)

                        if (
                            parsed_link.hostname
                            and parsed_link.hostname.lower()
                            in allowed_hosts
                            and relevant_link(link, keywords)
                            and link.split("#")[0] not in visited
                        ):
                            queue.append((link, depth + 1))

            else:
                raise ValueError(
                    f"Unsupported content type: {content_type}"
                )

        except Exception as exc:
            error_records.append(
                {
                    "Source_URL": normalized_url,
                    "Error": str(exc),
                    "Occurred_UTC": utc_now(),
                }
            )

    return source_records, evidence_records, error_records


def collect_ing_sector_guidance(
    guidance_url: str,
    sector_config: dict[str, Any],
    settings: BuildSettings,
    source_records: list[dict[str, Any]],
    evidence_records: list[dict[str, Any]],
    error_records: list[dict[str, Any]],
    extracted_directory: Path,
) -> None:
    """
    Collect public ING sector guidance separately from customer evidence.

    Only pages below the configured sector URL are followed.
    Podcast and audio-related pages are excluded.
    """
    if not guidance_url:
        return

    parsed_root = urlparse(guidance_url)

    if parsed_root.scheme not in {"http", "https"}:
        raise ValueError(
            "ING sector guidance URL must use HTTP or HTTPS."
        )

    if not parsed_root.hostname:
        raise ValueError(
            "ING sector guidance URL has no hostname."
        )

    hostname = parsed_root.hostname.lower()

    if not (
        hostname == "ing.nl"
        or hostname.endswith(".ing.nl")
    ):
        raise ValueError(
            "ING sector guidance must use an approved ing.nl URL."
        )

    excluded_keywords = sector_config.get(
        "excluded_ing_content_keywords",
        [],
    )

    max_pages = int(
        sector_config.get(
            "ing_sector_guidance_max_pages",
            30,
        )
    )

    max_depth = int(
        sector_config.get(
            "ing_sector_guidance_max_depth",
            2,
        )
    )

    allowed_hosts = {hostname}
    queue = deque([(guidance_url, 0)])
    visited: set[str] = set()
    session = requests.Session()

    ing_extract_directory = (
        extracted_directory / "ing_public_sector_guidance"
    )
    ing_extract_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    ing_page_count = 0

    while queue and ing_page_count < max_pages:
        url, depth = queue.popleft()
        normalized_url = url.split("#")[0]

        if normalized_url in visited:
            continue

        if not is_allowed_ing_child_url(
            guidance_url,
            normalized_url,
            excluded_keywords,
        ):
            continue

        visited.add(normalized_url)

        try:
            content, content_type, final_url = fetch_url(
                session=session,
                url=normalized_url,
                allowed_hosts=allowed_hosts,
                settings=settings,
            )

            is_pdf = (
                content_type == "application/pdf"
                or final_url.lower()
                .split("?")[0]
                .endswith(".pdf")
                or content.startswith(b"%PDF")
            )

            if is_pdf:
                title, pages, tables = extract_pdf(
                    content,
                    settings.max_text_characters_per_source,
                )

                if contains_excluded_content(
                    final_url,
                    title,
                    excluded_keywords,
                ):
                    continue

                source_id = add_source(
                    source_records=source_records,
                    evidence_records=evidence_records,
                    source_url=final_url,
                    title=title,
                    source_type="PDF",
                    source_group=(
                        "ING_Public_Sector_Guidance"
                    ),
                    content_type=content_type,
                    content=content,
                    text_records=pages,
                    table_records=tables,
                )

                extracted_text = "\n\n".join(
                    (
                        f"Page {page['page']}\n"
                        f"{page['text']}"
                    )
                    for page in pages
                )

                (
                    ing_extract_directory
                    / f"{source_id}.txt"
                ).write_text(
                    extracted_text,
                    encoding="utf-8",
                )

                ing_page_count += 1
                continue

            if content_type not in {
                "text/html",
                "application/xhtml+xml",
                "",
            }:
                raise ValueError(
                    f"Unsupported ING content type: "
                    f"{content_type}"
                )

            title, text, tables, links = extract_html(
                content=content,
                source_url=final_url,
                maximum_characters=(
                    settings.max_text_characters_per_source
                ),
            )

            if contains_excluded_content(
                final_url,
                title,
                excluded_keywords,
            ):
                continue

            text_records = [
                {
                    "page": "",
                    "section": title or "ING sector page",
                    "text": text,
                    "evidence_type": "HTML_TEXT",
                }
            ]

            table_records = [
                {
                    "page": "",
                    "table_number": table_number,
                    "text": table_text,
                }
                for table_number, table_text in enumerate(
                    tables,
                    start=1,
                )
            ]

            source_id = add_source(
                source_records=source_records,
                evidence_records=evidence_records,
                source_url=final_url,
                title=title,
                source_type="HTML",
                source_group="ING_Public_Sector_Guidance",
                content_type=content_type,
                content=content,
                text_records=text_records,
                table_records=table_records,
            )

            (
                ing_extract_directory
                / f"{source_id}.txt"
            ).write_text(
                text,
                encoding="utf-8",
            )

            ing_page_count += 1

            if depth < max_depth:
                for link in links:
                    clean_link = link.split("#")[0]

                    if (
                        clean_link not in visited
                        and is_allowed_ing_child_url(
                            root_url=guidance_url,
                            candidate_url=clean_link,
                            excluded_keywords=excluded_keywords,
                        )
                    ):
                        queue.append(
                            (clean_link, depth + 1)
                        )

        except Exception as exc:
            error_records.append(
                {
                    "Source_Group": (
                        "ING_Public_Sector_Guidance"
                    ),
                    "Source_URL": normalized_url,
                    "Error": str(exc),
                    "Occurred_UTC": utc_now(),
                }
            )


def evidence_matches_topic(
    evidence_text: str,
    topic_keywords: list[str],
) -> list[str]:
    lowered = evidence_text.lower()

    return [
        keyword
        for keyword in topic_keywords
        if keyword.lower() in lowered
    ]


def concise_excerpt(
    text: str,
    matched_keywords: list[str],
    maximum_length: int = 1200,
) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()

    if not normalized:
        return ""

    if not matched_keywords:
        return normalized[:maximum_length]

    lowered = normalized.lower()
    first_position = min(
        (
            lowered.find(keyword.lower())
            for keyword in matched_keywords
            if lowered.find(keyword.lower()) >= 0
        ),
        default=0,
    )

    start = max(0, first_position - 250)
    end = min(
        len(normalized),
        start + maximum_length,
    )

    return normalized[start:end]


def build_customer_ing_mapping(
    evidence_records: list[dict[str, Any]],
    mapping_topics: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """
    Map customer public evidence to ING public sector guidance.

    Every ING guidance item is retained. If no corresponding customer
    evidence exists, customer columns remain blank.
    """
    customer_evidence = [
        item
        for item in evidence_records
        if item.get("Source_Group") in {
            "Customer_Public",
            "Customer_Public_Upload",
        }
    ]

    ing_evidence = [
        item
        for item in evidence_records
        if item.get("Source_Group")
        == "ING_Public_Sector_Guidance"
    ]

    mappings: list[dict[str, Any]] = []

    for topic_name, keywords in mapping_topics.items():
        topic_ing_evidence: list[
            tuple[dict[str, Any], list[str]]
        ] = []

        for ing_item in ing_evidence:
            matched = evidence_matches_topic(
                str(ing_item.get("Evidence_Text", "")),
                keywords,
            )

            if matched:
                topic_ing_evidence.append(
                    (ing_item, matched)
                )

        if not topic_ing_evidence:
            continue

        topic_customer_evidence: list[
            tuple[dict[str, Any], list[str]]
        ] = []

        for customer_item in customer_evidence:
            matched = evidence_matches_topic(
                str(
                    customer_item.get(
                        "Evidence_Text",
                        "",
                    )
                ),
                keywords,
            )

            if matched:
                topic_customer_evidence.append(
                    (customer_item, matched)
                )

        best_customer_item = None
        best_customer_matches: list[str] = []

        if topic_customer_evidence:
            best_customer_item, best_customer_matches = max(
                topic_customer_evidence,
                key=lambda item: len(item[1]),
            )

        for ing_item, ing_matches in topic_ing_evidence:
            customer_found = (
                best_customer_item is not None
            )

            mappings.append(
                {
                    "Mapping_ID": (
                        f"MAP{len(mappings) + 1:04d}"
                    ),
                    "Topic": topic_name,
                    "Mapping_Status": (
                        "Mapped"
                        if customer_found
                        else "No customer mapping found"
                    ),
                    "Matched_Keywords": ", ".join(
                        sorted(
                            set(
                                ing_matches
                                + best_customer_matches
                            )
                        )
                    ),
                    "Customer_Source_ID": (
                        best_customer_item["Source_ID"]
                        if customer_found
                        else ""
                    ),
                    "Customer_Source_URL": (
                        best_customer_item["Source_URL"]
                        if customer_found
                        else ""
                    ),
                    "Customer_Page": (
                        best_customer_item["Page"]
                        if customer_found
                        else ""
                    ),
                    "Customer_Evidence": (
                        concise_excerpt(
                            best_customer_item[
                                "Evidence_Text"
                            ],
                            best_customer_matches,
                        )
                        if customer_found
                        else ""
                    ),
                    "ING_Source_ID": ing_item[
                        "Source_ID"
                    ],
                    "ING_Source_URL": ing_item[
                        "Source_URL"
                    ],
                    "ING_Page": ing_item["Page"],
                    "ING_Guidance_Evidence": (
                        concise_excerpt(
                            ing_item["Evidence_Text"],
                            ing_matches,
                        )
                    ),
                    "Interpretation_Status": (
                        "Evidence mapping only"
                    ),
                }
            )

    return mappings


def process_uploaded_pdfs(
    uploaded_pdfs: list[tuple[str, bytes]],
    settings: BuildSettings,
    raw_directory: Path,
    source_records: list[dict[str, Any]],
    evidence_records: list[dict[str, Any]],
    error_records: list[dict[str, Any]],
) -> None:
    for original_name, content in uploaded_pdfs:
        try:
            if len(content) > settings.max_download_bytes:
                raise ValueError("Uploaded PDF exceeds size limit.")

            if not content.startswith(b"%PDF"):
                raise ValueError("Uploaded file is not a PDF.")

            title, pages, tables = extract_pdf(
                content,
                settings.max_text_characters_per_source,
            )

            source_url = f"RM uploaded public file: {original_name}"

            source_id = add_source(
            source_records=source_records,
            evidence_records=evidence_records,
            source_url=source_url,
            title=title or original_name,
            source_type="UPLOADED_PDF",
            source_group="Customer_Public_Upload",
            content_type="application/pdf",
            content=content,
            text_records=pages,
            table_records=tables,
            )

            stored_name = (
                f"{source_id}_{safe_name(original_name)}"
            )
            (raw_directory / stored_name).write_bytes(content)

        except Exception as exc:
            error_records.append(
                {
                    "Source_URL": original_name,
                    "Error": str(exc),
                    "Occurred_UTC": utc_now(),
                }
            )


def find_nearest_year(
    text: str,
    value_position: int,
) -> str:
    """
    Return the year nearest to a numeric value in the evidence excerpt.
    """
    year_matches = list(YEAR_PATTERN.finditer(text))

    if not year_matches:
        return ""

    nearest_match = min(
        year_matches,
        key=lambda match: abs(
            match.start() - value_position
        ),
    )

    return nearest_match.group(1)


def find_numeric_mentions(
    evidence_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Find numeric mentions near ESG-related evidence.

    These are not verified KPIs. Agent 1 must use the source excerpt,
    source URL and page before presenting any value as a company fact.
    """
    records: list[dict[str, Any]] = []

    general_value_pattern = re.compile(
        r"""
        (?P<value>
            -?
            \d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?
            |
            -?\d+(?:\.\d+)?
        )
        \s*
        (?P<unit>
            %|
            tCO2e|
            ktCO2e|
            MtCO2e|
            tonnes?\s+CO2e|
            metric\s+tons?\s+CO2e|
            MWh|
            GWh|
            kWh|
            GJ|
            m3|
            megalitres?|
            tonnes?|
            metric\s+tons?|
            kilograms?|
            kg|
            kilometres?|
            km|
            vehicles?|
            employees?|
            FTE
        )
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    for evidence in evidence_records:
        text = str(evidence.get("Evidence_Text", ""))

        for match in general_value_pattern.finditer(text):
            context_start = max(0, match.start() - 300)
            context_end = min(len(text), match.end() + 500)

            excerpt = re.sub(
                r"\s+",
                " ",
                text[context_start:context_end],
            ).strip()

            value_position_in_excerpt = (
                match.start() - context_start
            )
            
            year = find_nearest_year(
                excerpt,
                value_position_in_excerpt,
            )
            records.append(
                {
                    "Candidate_ID": (
                        f"V{len(records) + 1:05d}"
                    ),
                    "Value": match.group("value"),
                    "Unit": match.group("unit"),
                    "Year": year,
                    "Source_ID": evidence["Source_ID"],
                    "Source_URL": evidence["Source_URL"],
                    "Page": evidence["Page"],
                    "Evidence_Excerpt": excerpt,
                    "Extraction_Method": evidence[
                        "Evidence_Type"
                    ],
                    "Evidence_Status": "AutomaticallyExtracted",
                }
            )

    unique_records: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for record in records:
        key = (
            record["Value"],
            record["Unit"],
            record["Year"],
            record["Source_ID"],
            record["Page"],
            record["Evidence_Excerpt"],
        )

        if key not in seen:
            seen.add(key)
            unique_records.append(record)

    return unique_records


def write_excel(
    workbook_path: Path,
    request: BuildRequest,
    source_records: list[dict[str, Any]],
    evidence_records: list[dict[str, Any]],
    value_candidates: list[dict[str, Any]],
    customer_ing_mapping: list[dict[str, Any]],
    sector_reference: pd.DataFrame,
    error_records: list[dict[str, Any]],
) -> None:
    request_data = asdict(request)

    request_data["approved_source_urls"] = "\n".join(
        request.approved_source_urls
    )
    
    customer_sources = [
    source
    for source in source_records
    if source.get("Source_Group") in {
        "Customer_Public",
        "Customer_Public_Upload",
    }
]

    ing_sources = [
        source
        for source in source_records
        if source.get("Source_Group")
        == "ING_Public_Sector_Guidance"
    ]
    
    tables = {
        "Request": pd.DataFrame([request_data]),
        "Customer_Sources": pd.DataFrame(
            customer_sources
        ),
        "ING_Sector_Guidance": pd.DataFrame(
            ing_sources
        ),
        "Evidence": pd.DataFrame(evidence_records),
        "Value_Candidates": pd.DataFrame(
            value_candidates
        ),
        "Customer_ING_Mapping": pd.DataFrame(
            customer_ing_mapping
        ),
        "Sector_Source_Guidance": sector_reference,
        "Errors": pd.DataFrame(error_records),
    }
        
    
    # tables = {
    #     "Request": pd.DataFrame([request_data]),
    #     "Sources": pd.DataFrame(source_records),
    #     "Evidence": pd.DataFrame(evidence_records),
    #     "Value_Candidates": pd.DataFrame(value_candidates),
    #     "Sector_Source_Guidance": sector_reference,
    #     "Errors": pd.DataFrame(error_records),
    # }

    with pd.ExcelWriter(
        workbook_path,
        engine="openpyxl",
    ) as writer:
        for sheet_name, table in tables.items():
            if table.empty:
                table = pd.DataFrame(
                    {
                        "Information": [
                            "No records were produced for this section."
                        ]
                    }
                )

            table.to_excel(
                writer,
                sheet_name=sheet_name,
                index=False,
            )

        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions

            for column in worksheet.columns:
                column_letter = column[0].column_letter

                maximum_length = max(
                    (
                        len(str(cell.value or ""))
                        for cell in column[:100]
                    ),
                    default=12,
                )

                worksheet.column_dimensions[
                    column_letter
                ].width = min(
                    max(maximum_length + 2, 12),
                    60,
                )


def write_markdown(
    markdown_path: Path,
    request: BuildRequest,
    source_records: list[dict[str, Any]],
    evidence_records: list[dict[str, Any]],
    value_candidates: list[dict[str, Any]],
    sector_reference: pd.DataFrame,
    customer_ing_mapping: list[dict[str, Any]],
    error_records: list[dict[str, Any]],
) -> None:
    lines = [
        f"# Public ESG Evidence Pack: {request.customer_name}",
        "",
        f"Request ID: {request.request_id}",
        f"Sector: {request.sector}",
        f"Website: {request.website}",
        f"Generated UTC: {utc_now()}",
        "",
        "## Important usage rule",
        "",
        (
            "This evidence pack was produced through automated "
            "extraction of approved public sources."
        ),
        "",
        (
            "Numeric values are automatically identified candidates. "
            "They must be interpreted together with the source URL, "
            "page and evidence excerpt."
        ),
        "",
        (
            "Sector source guidance identifies potentially relevant "
            "source families. It does not prove that the customer "
            "follows, meets or is required to follow those sources."
        ),
        "",
        "## Sector source guidance",
        "",
    ]

    for _, row in sector_reference.iterrows():
        lines.extend(
            [
                f"Sector: {row['Display_Name']}",
                "",
                "Relevant source families:",
                "",
                str(row["KPIs_Data_Sources"]),
                "",
            ]
        )

    lines.extend(["## Public customer sources", ""])

    if not source_records:
        lines.extend(
            [
                "No public customer sources were successfully extracted.",
                "",
            ]
        )

    for source in source_records:
        lines.extend(
            [
                (
                    f"### [{source['Source_ID']}] "
                    f"{source['Title'] or 'Untitled source'}"
                ),
                "",
                f"Source URL: {source['Source_URL']}",
                f"Source type: {source['Source_Type']}",
                f"Retrieved: {source['Retrieved_UTC']}",
                f"SHA256: {source['SHA256']}",
                "",
            ]
        )

    lines.extend(
        [
            "## Automatically extracted value candidates",
            "",
        ]
    )

    if not value_candidates:
        lines.extend(
            [
                "No structured numeric value candidates were extracted.",
                "",
            ]
        )

    for candidate in value_candidates:
        citation = f"[{candidate['Source_ID']}"

        if candidate["Page"] not in ("", None):
            citation += f", page {candidate['Page']}"

        citation += "]"

        lines.extend(
            [
                f"### Candidate {candidate['Candidate_ID']}",
                "",
                (
                    f"Value: {candidate['Value']} "
                    f"{candidate['Unit']}"
                ),
                (
                    "Year: "
                    + (
                        candidate["Year"]
                        if candidate["Year"]
                        else "Not identified"
                    )
                ),
                f"Evidence: {candidate['Evidence_Excerpt']}",
                f"Citation: {citation}",
                f"Source URL: {candidate['Source_URL']}",
                "",
            ]
        )

    lines.extend(["## Extracted public evidence", ""])
    
    lines.extend(
    [
        "## Customer evidence mapped to ING public sector guidance",
        "",
        (
            "This section maps extracted customer evidence to "
            "topics found on the ING public sector website."
        ),
        "",
        (
            "A mapping indicates topic similarity only. It does not "
            "prove alignment with ING policy, eligibility for a "
            "product, or compliance with a standard."
        ),
        "",
    ]
    )

    if not customer_ing_mapping:
        lines.extend(
            [
                "No customer-to-ING sector mapping was produced.",
                "",
            ]
        )
    
    for mapping in customer_ing_mapping:
        lines.extend(
            [
                f"### {mapping['Topic']}",
                "",
                (
                    "Mapping status: "
                    f"{mapping['Mapping_Status']}"
                ),
                "",
                "Customer evidence:",
                "",
                mapping["Customer_Evidence"],
                "",
                (
                    "Customer citation: "
                    f"[{mapping['Customer_Source_ID']}"
                    + (
                        f", page {mapping['Customer_Page']}"
                        if mapping["Customer_Page"]
                        not in ("", None)
                        else ""
                    )
                    + "]"
                    if mapping["Customer_Source_ID"]
                    else "Customer evidence not found"
                ),
                "",
                (
                    "Customer source URL: "
                    f"{mapping['Customer_Source_URL']}"
                ),
                "",
                "ING public sector guidance:",
                "",
                mapping["ING_Guidance_Evidence"],
                "",
                (
                    "ING citation: "
                    f"[{mapping['ING_Source_ID']}"
                    + (
                        f", page {mapping['ING_Page']}"
                        if mapping["ING_Page"]
                        not in ("", None)
                        else ""
                    )
                    + "]"
                ),
                "",
                (
                    "ING source URL: "
                    f"{mapping['ING_Source_URL']}"
                ),
                "",
            ]
        )
    


    for evidence in evidence_records:
        citation = f"[{evidence['Source_ID']}"

        if evidence["Page"] not in ("", None):
            citation += f", page {evidence['Page']}"

        citation += "]"

        lines.extend(
            [
                (
                    f"### {citation} "
                    f"{evidence['Section'] or evidence['Evidence_Type']}"
                ),
                "",
                evidence["Evidence_Text"],
                "",
                f"Source URL: {evidence['Source_URL']}",
                "",
            ]
        )

    lines.extend(
        [
            "## Extraction errors and limitations",
            "",
        ]
    )

    if not error_records:
        lines.extend(
            [
                "No extraction errors were recorded.",
                "",
            ]
        )
    else:
        for error in error_records:
            lines.extend(
                [
                    f"Source: {error['Source_URL']}",
                    f"Error: {error['Error']}",
                    "",
                ]
            )

    markdown_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def create_zip(
    output_directory: Path,
    zip_path: Path,
) -> None:
    with zipfile.ZipFile(
        zip_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for file_path in output_directory.rglob("*"):
            if file_path.is_file() and file_path != zip_path:
                archive.write(
                    file_path,
                    file_path.relative_to(output_directory),
                )


def build_evidence_pack(
    request: BuildRequest,
    sector_config: dict[str, Any],
    sector_source_file: Path,
    output_directory: Path,
    uploaded_pdfs: list[tuple[str, bytes]] | None = None,
) -> dict[str, Path]:
    settings = BuildSettings()
    output_directory.mkdir(parents=True, exist_ok=True)

    raw_directory = output_directory / "raw_public_pdfs"
    extracted_directory = output_directory / "extracted_text"

    raw_directory.mkdir(exist_ok=True)
    extracted_directory.mkdir(exist_ok=True)

    sources, evidence, errors = collect_web_sources(
        request,
        sector_config["keywords"],
        settings,
        raw_directory,
        extracted_directory,
    )

    process_uploaded_pdfs(
        uploaded_pdfs or [],
        settings,
        raw_directory,
        sources,
        evidence,
        errors,
    )
    collect_ing_sector_guidance(
    guidance_url=request.ing_sector_guidance_url,
    sector_config=sector_config,
    settings=settings,
    source_records=sources,
    evidence_records=evidence,
    error_records=errors,
    extracted_directory=extracted_directory,
    )

    customer_ing_mapping = build_customer_ing_mapping(
        evidence_records=evidence,
        mapping_topics=sector_config.get(
            "mapping_topics",
            {},
        ),
    )

    sector_reference = load_sector_reference(
        sector_source_file,
        request.sector,
    )

    value_candidates = find_numeric_mentions(evidence)

    customer_name = safe_name(request.customer_name)

    workbook_path = (
        output_directory / f"ESG_data_{customer_name}.xlsx"
    )

    markdown_path = (
        output_directory / f"ESG_evidence_{customer_name}.md"
    )

    manifest_path = output_directory / "run_manifest.json"
    instructions_path = output_directory / "README_FOR_RM.txt"

    zip_path = (
        output_directory
        / f"ESG_Evidence_Pack_{customer_name}.zip"
    )

    write_excel(
    workbook_path=workbook_path,
    request=request,
    source_records=sources,
    evidence_records=evidence,
    value_candidates=value_candidates,
    customer_ing_mapping=customer_ing_mapping,
    sector_reference=sector_reference,
    error_records=errors,
    )

    write_markdown(
    markdown_path=markdown_path,
    request=request,
    source_records=sources,
    evidence_records=evidence,
    value_candidates=value_candidates,
    customer_ing_mapping=customer_ing_mapping,
    sector_reference=sector_reference,
    error_records=errors,
   )

    manifest_path.write_text(
        json.dumps(
            {
                "request": asdict(request),
                "generated_utc": utc_now(),
                "sector_source_catalogue": (
                    sector_source_file.name
                ),
                "source_count": len(sources),
                "evidence_record_count": len(evidence),
                "value_candidate_count": len(
                    value_candidates
                ),
                "ing_sector_guidance_url": (
                request.ing_sector_guidance_url
                ),
                "customer_ing_mapping_count": len(
                    customer_ing_mapping
                ),
                "error_count": len(errors),
                "important_limitations": [
                    (
                        "Sector source guidance is not a "
                        "quantitative KPI taxonomy."
                    ),
                    (
                        "Value candidates are automatically "
                        "extracted and must be supported by "
                        "their source excerpts."
                    ),
                    (
                        "Scanned PDFs may require OCR and may "
                        "not produce extractable evidence."
                    ),
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    instructions_path.write_text(
        (
            "BB Sustainability Evidence Pack\n\n"
            "1. Extract this ZIP file.\n"
            "2. Upload ESG_data_<customer>.xlsx to SharePoint.\n"
            "3. Upload ESG_evidence_<customer>.md to SharePoint.\n"
            "4. Upload permitted public PDFs where required.\n"
            "5. Wait for SharePoint indexing.\n"
            "6. Run the relevant sector Agent 1.\n"
            "7. Save Agent 1 output to its SharePoint folder.\n"
            "8. Run Agent 2 using only Agent 1 output.\n\n"
            "The Sector_Source_Guidance sheet contains relevant "
            "source families, not verified customer facts.\n\n"
            "The Value_Candidates sheet contains automatically "
            "extracted values. Values must be used together with "
            "their source URL, page and evidence excerpt.\n"
        ),
        encoding="utf-8",
    )

    create_zip(
        output_directory=output_directory,
        zip_path=zip_path,
    )

    return {
        "excel": workbook_path,
        "markdown": markdown_path,
        "manifest": manifest_path,
        "zip": zip_path,
    }