# DeviceCheck Midscene integration

Official `@midscene/core` 1.17.7 Agent with a read-only screenshot interface.
Model requests use `createOpenAIClient` and a private stdio bridge to the existing
CodeBuddy CLI. Credentials stay in the existing process/keychain path; no HTTP
model proxy or additional API key is required.

Install: `npm ci --prefix midscene --registry=https://registry.npmjs.org`

Synthetic query: `python3 midscene_bridge.py --model hy4std`
Synthetic coordinate test: `python3 midscene_bridge.py --model hy4std --locate`

The recovery flow uses `aiQuery` to classify an empty store page. It exposes no
Midscene actions. Existing Appium code performs only bounded scrolling after
screenshot revalidation. Model-family `gpt-5` supplies the structured extraction
protocol; the actual provider remains the selected CodeBuddy model. This is a
custom compatibility bridge, not an officially supported CodeBuddy provider.
Reports are disabled to avoid duplicate screenshot persistence. No usage/token
counts are fabricated by the bridge. CLI process reuse is not implemented.
