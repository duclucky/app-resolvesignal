"""Install the fixed, offline reference set in an explicitly selected database."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.store import Store
from src.reference_examples import install

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',required=True,type=Path)
    args=parser.parse_args()
    if not args.database.is_absolute():parser.error('Use an absolute database path.')
    store=Store(args.database);bid=install(store)
    print(json.dumps({'batch_id':bid,'cases':len(store.batch(bid)),'kind':'fictional_reference_examples','provider_calls':0}))
