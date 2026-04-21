
import argparse
from pathlib import Path
from typing import List
import pandas as pd

EU_COUNTRIES = {
    'AT','BE','BG','HR','CY','CZ','DK','EE','FI','FR','DE','GR','HU','IE','IT',
    'LV','LT','LU','MT','NL','PL','PT','RO','SK','SI','ES','SE'
}

STRIPE_REQUIRED_COLUMNS = {
    'id',
    'Status',
    'Fee',
    'Converted Amount',
    'Currency',
    'Card Brand',
    'Card Issue Country',
}

UNLIMIT_REQUIRED_COLUMNS = {
    'Order ID',
    'Type',
    'Transaction Currency',
    'Settlement Amount',
    'Interchange Fee',
    'Scheme Fee',
    'Acquirer Fee',
    'Card Brand',
    'Region',
}

def load_excel_or_csv(path: Path):
    suffix = path.suffix.lower()
    if suffix in ['.xlsx', '.xls']:
        return pd.ExcelFile(path)
    if suffix == '.csv':
        return pd.read_csv(path)
    raise ValueError(f'Unsupported file format: {suffix}')

def infer_terminal_from_name(name: str) -> str:
    lower = name.lower()
    if 'stripe' in lower:
        return 'Stripe'
    if 'unlimit' in lower and 'uk' in lower:
        return 'Unlimit UK'
    if 'unlimit' in lower and 'eu' in lower:
        return 'Unlimit EU'
    if 'unlimit' in lower:
        return 'Unlimit'
    return 'Unknown'

def normalize_region(value: str) -> str:
    if pd.isna(value):
        return 'International'
    text = str(value).strip().lower()
    mapping = {
        'domestic': 'Domestic',
        'domestik': 'Domestic',
        'eu': 'EU',
        'europe': 'EU',
        'international': 'International',
        'intl': 'International',
    }
    return mapping.get(text, str(value).strip())

def get_region_from_country(issue_country: str, domestic_country: str) -> str:
    if pd.isna(issue_country):
        return 'International'
    country = str(issue_country).strip().upper()
    domestic_country = domestic_country.strip().upper()

    if country == domestic_country:
        return 'Domestic'
    if country in EU_COUNTRIES:
        return 'EU'
    return 'International'

def format_brand(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower()

def format_currency(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.upper()

def aggregate_report(df: pd.DataFrame, id_column: str) -> pd.DataFrame:
    report = (
        df.groupby(['Card Brand', 'Currency', 'Card Region', 'Terminal'], dropna=False)
          .agg(
              sample_size=(id_column, 'count'),
              avg_mdr_pct=('mdr_pct', 'mean')
          )
          .reset_index()
    )
    report['avg_mdr_pct'] = report['avg_mdr_pct'].round(2)
    report = report.sort_values(
        by=['Card Brand', 'Currency', 'Card Region', 'Terminal']
    ).reset_index(drop=True)
    return report

def process_stripe_df(df: pd.DataFrame, domestic_country: str, terminal: str = 'Stripe') -> pd.DataFrame:
    missing = STRIPE_REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f'Stripe file is missing columns: {sorted(missing)}')

    work = df[df['Status'].astype(str).str.strip().str.lower() == 'paid'].copy()

    work['Fee'] = pd.to_numeric(work['Fee'], errors='coerce')
    work['Converted Amount'] = pd.to_numeric(work['Converted Amount'], errors='coerce')

    work = work[
        (work['Converted Amount'].notna()) &
        (work['Converted Amount'] != 0) &
        (work['Fee'].notna())
    ].copy()

    # В отчете валютой считается исходная валюта транзакции, но сам расчет идет по Converted Amount.
    work['mdr_pct'] = (work['Fee'].abs() / work['Converted Amount']) * 100
    work['Card Brand'] = format_brand(work['Card Brand'])
    work['Currency'] = format_currency(work['Currency'])
    work['Card Region'] = work['Card Issue Country'].apply(
        lambda x: get_region_from_country(x, domestic_country)
    )
    work['Terminal'] = terminal

    return aggregate_report(work, 'id')

def detect_unlimit_terminal(sheet_name: str, file_name: str) -> str:
    sheet = str(sheet_name).lower()
    if 'uk' in sheet:
        return 'Unlimit UK'
    if 'eu' in sheet:
        return 'Unlimit EU'

    file_lower = str(file_name).lower()
    if 'uk' in file_lower and 'eu' not in file_lower:
        return 'Unlimit UK'
    if 'eu' in file_lower and 'uk' not in file_lower:
        return 'Unlimit EU'

    return 'Unlimit'

def process_unlimit_df(df: pd.DataFrame, terminal: str) -> pd.DataFrame:
    missing = UNLIMIT_REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f'Unlimit file is missing columns: {sorted(missing)}')

    work = df[df['Type'].astype(str).str.contains('purchase', case=False, na=False)].copy()

    for col in ['Interchange Fee', 'Scheme Fee', 'Acquirer Fee', 'Settlement Amount']:
        work[col] = pd.to_numeric(work[col], errors='coerce')

    work['fee_sum'] = (
        work['Interchange Fee'].fillna(0) +
        work['Scheme Fee'].fillna(0) +
        work['Acquirer Fee'].fillna(0)
    )

    work = work[
        (work['Settlement Amount'].notna()) &
        (work['Settlement Amount'] != 0)
    ].copy()

    # В отчете валютой считается исходная валюта транзакции, но сам расчет идет по Settlement Amount.
    work['mdr_pct'] = (work['fee_sum'].abs() / work['Settlement Amount']) * 100
    work['Card Brand'] = format_brand(work['Card Brand'])
    work['Currency'] = format_currency(work['Transaction Currency'])
    work['Card Region'] = work['Region'].apply(normalize_region)
    work['Terminal'] = terminal

    return aggregate_report(work, 'Order ID')

def is_stripe_df(df: pd.DataFrame) -> bool:
    return STRIPE_REQUIRED_COLUMNS.issubset(set(df.columns))

def is_unlimit_df(df: pd.DataFrame) -> bool:
    return UNLIMIT_REQUIRED_COLUMNS.issubset(set(df.columns))

def process_file(path: Path, domestic_country: str = 'GB') -> pd.DataFrame:
    loaded = load_excel_or_csv(path)

    if isinstance(loaded, pd.DataFrame):
        df = loaded
        if is_stripe_df(df):
            terminal = infer_terminal_from_name(path.name)
            if terminal == 'Unknown':
                terminal = 'Stripe'
            return process_stripe_df(df, domestic_country=domestic_country, terminal=terminal)
        if is_unlimit_df(df):
            terminal = infer_terminal_from_name(path.name)
            if terminal == 'Unknown':
                terminal = 'Unlimit'
            return process_unlimit_df(df, terminal=terminal)
        raise ValueError('Could not detect file format for CSV input.')

    reports: List[pd.DataFrame] = []

    for sheet_name in loaded.sheet_names:
        df = loaded.parse(sheet_name)

        if is_stripe_df(df):
            terminal = infer_terminal_from_name(path.name)
            if terminal == 'Unknown':
                terminal = 'Stripe'
            reports.append(
                process_stripe_df(df, domestic_country=domestic_country, terminal=terminal)
            )
        elif is_unlimit_df(df):
            terminal = detect_unlimit_terminal(sheet_name, path.name)
            reports.append(process_unlimit_df(df, terminal=terminal))

    if not reports:
        raise ValueError('Could not detect Stripe or Unlimit structure in any sheet.')

    combined = pd.concat(reports, ignore_index=True)

    final = (
        combined.groupby(['Card Brand', 'Currency', 'Card Region', 'Terminal'], dropna=False)
                .agg(
                    sample_size=('sample_size', 'sum'),
                    avg_mdr_pct=('avg_mdr_pct', 'mean')
                )
                .reset_index()
    )

    final['avg_mdr_pct'] = final['avg_mdr_pct'].round(2)
    final = final.sort_values(
        by=['Terminal', 'Card Brand', 'Currency', 'Card Region']
    ).reset_index(drop=True)
    return final

def main():
    parser = argparse.ArgumentParser(
        description='Universal MDR parser for Stripe and Unlimit exports'
    )
    parser.add_argument('input_file', help='Path to Excel/CSV input file')
    parser.add_argument(
        '-o', '--output',
        default='mdr_report.xlsx',
        help='Path to output Excel file'
    )
    parser.add_argument(
        '--domestic-country',
        default='GB',
        help='Domestic country ISO code for Stripe region mapping, default: GB'
    )

    args = parser.parse_args()

    input_path = Path(args.input_file)
    output_path = Path(args.output)

    final = process_file(input_path, domestic_country=args.domestic_country)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    final.to_excel(output_path, index=False)

    print(f'Report created: {output_path}')
    print(f'Rows in report: {len(final)}')

if __name__ == '__main__':
    main()
