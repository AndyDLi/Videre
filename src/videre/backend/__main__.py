import uvicorn

from .application import create_application


def main() -> None:
    uvicorn.run(create_application(), host="0.0.0.0", port=8000, log_config=None)


if __name__ == "__main__":
    main()
