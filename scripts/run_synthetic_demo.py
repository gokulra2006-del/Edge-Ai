"""Run the existing dashboard with the newly trained synthetic profile, locally."""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    os.environ['EDGE_AI_MODEL_PROFILE'] = 'synthetic'
    os.environ['FIREBASE_DATABASE_URL'] = ''
    from src.modules.dashboard.app import run_dashboard_server, STREAMER
    print('SYNTHETIC MODEL DEMO: generated-data accuracy is not real-world validation.', flush=True)
    server = run_dashboard_server(host='127.0.0.1', port=args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        STREAMER.stop()
        server.server_close()


if __name__ == '__main__':
    main()
