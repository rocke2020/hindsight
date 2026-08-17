.PHONY: start_dev

start_dev:
	PATH="$$HOME/.local/bin:$$PATH" UV_NO_SYNC=1 \
		./scripts/dev/start.sh
