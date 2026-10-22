import os
from pathlib import Path
from dotenv import dotenv_values, set_key

ROOT=Path(__file__).resolve().parents[1]
ENV=Path(os.environ.get('APP_ENV_FILE',str(ROOT/'.env')))


def data_directory():
    return Path(os.environ.get('APP_DATA_DIR',str(ROOT/'data')))


def settings():
    return {**dotenv_values(ENV),**os.environ}


def save_settings(values):
    if os.environ.get('APP_SETTINGS_LOCKED')=='true':
        raise ValueError('Settings are managed by the server administrator.')
    allowed={'NEBIUS_API_KEY','TAVILY_API_KEY','NEBIUS_MODEL','LIVE_CALLS_ENABLED','NEBIUS_BUDGET_USD','TAVILY_CREDIT_CAP',
             'LANGSMITH_API_KEY','LANGSMITH_WORKSPACE_ID','LANGSMITH_ENABLED'}
    for name,maximum in [('NEBIUS_BUDGET_USD',5),('TAVILY_CREDIT_CAP',200)]:
        if name in values:
            try:number=float(values[name])
            except (TypeError,ValueError):raise ValueError('Usage caps must be numbers.') from None
            if not __import__('math').isfinite(number) or not 0<=number<=maximum:raise ValueError('Usage cap is outside the local configuration range.')
    for key,value in values.items():
        if key in allowed and value is not None and str(value).strip():
            set_key(ENV,key,str(value).strip())


def status():
    s=settings()
    return {'nebius_configured':bool(s.get('NEBIUS_API_KEY')),'tavily_configured':bool(s.get('TAVILY_API_KEY')),
            'langsmith_configured':bool(s.get('LANGSMITH_API_KEY')),'langsmith_enabled':s.get('LANGSMITH_ENABLED')=='true',
            'model':s.get('NEBIUS_MODEL',''),'live_enabled':s.get('LIVE_CALLS_ENABLED')=='true',
            'nebius_budget_usd':s.get('NEBIUS_BUDGET_USD','0'),'tavily_credit_cap':s.get('TAVILY_CREDIT_CAP','0'),
            'settings_managed':os.environ.get('APP_SETTINGS_LOCKED')=='true',
            'public_demo':os.environ.get('APP_PUBLIC_DEMO')=='true',
            'external_actions_enabled':os.environ.get('APP_EXTERNAL_ACTIONS_ENABLED','true')=='true'}
