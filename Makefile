.PHONY: help check dist release clean

help:
	@grep -E '^[a-z-]+:.*?## ' Makefile | sed 's/:.*## /\t/'

check:   ## validate the config files, no cluster access needed
	@./tools/validate.sh

dist: check  ## build the installer at dist/agentfence
	@./tools/build-installer.sh

release: dist  ## tag and push; the release workflow publishes the artefact
	@test -n "$(V)" || { echo "usage: make release V=v0.1.0"; exit 1; }
	@git tag -a "$(V)" -m "agentfence $(V)"
	@git push origin "$(V)"
	@echo "pushed $(V); watch: gh run watch"

clean:
	@rm -rf dist
