import pandas as pd
from sqlalchemy import (
    BigInteger,
    Column,
    Integer,
    MetaData,
    Table,
    Text,
    create_engine,
)

from src.config import config

engine = create_engine(f"sqlite:///{config.db_path}")
metadata = MetaData()

# --- seed tables ---

input_companies = Table(
    "input_companies",
    metadata,
    Column("name", Text),
    Column("crunchbase", Text),
    Column("domain", Text),
    Column("linkedin", Text),
    Column("pitchbook", Text),
    Column("twitter", Text),
)

canonical = Table(
    "canonical",
    metadata,
    Column("guru_permalink", Text, primary_key=True),
    Column("crunchbase", Text),
    Column("name", Text),
    Column("operating_status", Text),
    Column("acquired", Text),
    Column("company_type", Text),
    Column("short_description", Text),
    Column("address", Text),
    Column("founded_date", Text),
    Column("ipo_status", Text),
    Column("domain", Text),
    Column("linkedin", Text),
    Column("pitchbook", Text),
    Column("twitter", Text),
    Column("contact_email", Text),
    Column("contact_phone", Text),
    Column("num_employees", Text),
    Column("created_at", Text),
    Column("updated_at", Text),
)

enrichment_log = Table(
    "enrichment_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("company", Text),
    Column("source", Text),   # crunchbase | linkedin | both
    Column("status", Text),   # ok | failed | skipped
    Column("error", Text),
    Column("logged_at", Text),
)

# --- crunchbase landing ---

cb_companies = Table(
    "cb_companies",
    metadata,
    Column("permalink", Text, primary_key=True),
    Column("name", Text),
    Column("short_description", Text),    # api: about
    Column("full_description", Text),
    Column("website", Text),
    # founded_on NOT in CB response
    Column("operating_status", Text),
    Column("company_type", Text),
    Column("employee_count_range", Text), # api: num_employees — range string "101-250"
    Column("total_funding_usd", BigInteger),
    Column("ipo_status", Text),
    Column("last_funding_type", Text),
    Column("contact_email", Text),
    Column("contact_phone", Text),
    Column("acquired_by", Text),          # api: acquired_by.acquirer
    Column("social_media_links", Text),   # JSON array as text
    Column("enriched_at", Text),
)

cb_categories = Table(
    "cb_categories",
    metadata,
    Column("permalink", Text),
    Column("category_name", Text),        # api: industries[].value
    Column("category_slug", Text),        # api: industries[].id
)

cb_locations = Table(
    "cb_locations",
    metadata,
    # parsed from location[] array: [0]=city [1]=state [2]=country [3]=continent
    Column("permalink", Text),
    Column("city", Text),
    Column("state", Text),
    Column("country", Text),
    Column("continent", Text),
    Column("country_code", Text),
    Column("address", Text),              # flat string "City, State, Country, Continent"
)

cb_funding_rounds = Table(
    "cb_funding_rounds",
    metadata,
    Column("permalink", Text),
    Column("round_id", Text, primary_key=True),  # funding_rounds_list[].id
    Column("round_uuid", Text),
    Column("title", Text),
    Column("raised_amount_usd", BigInteger),
    Column("lead_investors", Text),       # JSON array as text
)

# --- linkedin landing ---
# no li_specialties table — specialties is a flat string stored inline

li_companies = Table(
    "li_companies",
    metadata,
    Column("handle", Text, primary_key=True),    # api: id (slug)
    Column("company_id", Text),                  # numeric LinkedIn ID
    Column("name", Text),
    Column("website", Text),
    Column("about", Text),
    Column("employee_count", Integer),           # api: employees_in_linkedin
    Column("company_size", Text),                # "11-50 employees"
    Column("founded_year", Integer),             # often null
    Column("organization_type", Text),
    Column("industries", Text),                  # flat string
    Column("specialties", Text),                 # flat comma string
    Column("headquarters", Text),
    Column("country_code", Text),
    Column("slogan", Text),
    Column("url", Text),
    Column("enriched_at", Text),
)

li_locations = Table(
    "li_locations",
    metadata,
    Column("handle", Text),
    Column("location", Text),                    # "Venice, California 90291, US"
)


def init_db() -> None:
    config.db_path.parent.mkdir(parents=True, exist_ok=True)
    metadata.create_all(engine)
    _seed_if_empty()


def _seed_if_empty() -> None:
    with engine.connect() as conn:
        if conn.execute(input_companies.select().limit(1)).fetchone() is None:
            df = pd.read_excel(config.xlsx_path, sheet_name="candidate_take_home", engine="calamine")
            df.to_sql("input_companies", conn, if_exists="append", index=False)
            conn.commit()

        if conn.execute(canonical.select().limit(1)).fetchone() is None:
            df = pd.read_excel(config.xlsx_path, sheet_name="database", engine="calamine")
            df = df.astype(str).replace("nan", None)
            df.to_sql("canonical", conn, if_exists="append", index=False)
            conn.commit()
