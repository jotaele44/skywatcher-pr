FEDERATION_PY ?= python3

.PHONY: federation-export federation-dashboard federation-package federation-validate export dashboard package validate offline

federation-export:
	$(FEDERATION_PY) scripts/offline_operator.py export

federation-dashboard:
	$(FEDERATION_PY) scripts/offline_operator.py dashboard

federation-package: federation-export federation-dashboard
	$(FEDERATION_PY) scripts/offline_operator.py package

federation-validate:
	$(FEDERATION_PY) scripts/offline_operator.py validate

export: federation-export

dashboard: federation-dashboard

package: federation-package

validate: federation-validate

offline: federation-package federation-validate
