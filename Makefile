.PHONY: check

# 完整本地验证；任一步失败即停止。前端只构建一次。
check:
	.venv/bin/python -m pytest -q
	PYTHONPATH=backend .venv/bin/python -m agentic_cm.capabilities validate
	npm --prefix frontend run check
