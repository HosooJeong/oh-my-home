"""Two live requests between public Jinju locations; no raw route/key/coordinate output."""
import argparse
from pathlib import Path

from app.routes import KakaoRoutes, RouteError, RouteInput


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', type=Path, required=True)
    args = parser.parse_args()
    client = KakaoRoutes(args.env_file)
    print('Configured:', client.status()['configured'])
    success = True
    for mode in ('walk', 'transit'):
        request = RouteInput.model_validate({'start': {'latitude': 35.18057, 'longitude': 128.10770},
                                            'end': {'latitude': 35.15080, 'longitude': 128.11896},
                                            'mode': mode})
        try:
            result = client.query(request)
            print({'mode': mode, 'status': 'verified_live', 'route_count': len(result['routes']),
                   'geometry_present': all(r['segments'] for r in result['routes']),
                   'llm_transfer': result['llm_transfer']})
        except RouteError as issue:
            success = False
            print({'mode': mode, **issue.public()})
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
