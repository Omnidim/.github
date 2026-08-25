<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./assets/logo-dark.png">
  <img alt="OmniDimension" src="./assets/logo-light.png" width="360">
</picture>

<br>

**Create your Free Voice AI Assistant**

Build an agent from a prompt, give it your tools and knowledge, then put it on a
phone number, a website, or a bulk campaign.

[Hosted MCP server](https://docs.omnidim.io/docs/mcp) &nbsp;·&nbsp;
[Documentation](https://docs.omnidim.io/docs) &nbsp;·&nbsp;
[Quickstart](https://docs.omnidim.io/docs/get-started/quickstart) &nbsp;·&nbsp;
[API reference](https://docs.omnidim.io/docs/api-reference) &nbsp;·&nbsp;
[Examples](https://github.com/Omnidim/examples) &nbsp;·&nbsp;
[Community on Discord](https://discord.gg/kdjzykMTHJ) &nbsp;·&nbsp;
[Dashboard](https://omnidim.io)

[![npm](https://img.shields.io/npm/v/%40omnidim-ai%2Fsdk?label=%40omnidim-ai%2Fsdk&color=00B3B3)](https://www.npmjs.com/package/@omnidim-ai/sdk)
[![PyPI](https://img.shields.io/pypi/v/omnidimension?label=omnidimension&color=00B3B3)](https://pypi.org/project/omnidimension/)
[![MCP server](https://img.shields.io/npm/v/%40omnidim-ai%2Fmcp-server?label=mcp-server&color=00B3B3)](https://www.npmjs.com/package/@omnidim-ai/mcp-server)

</div>

---

## Your first call

```bash
npm install @omnidim-ai/sdk
```

```ts
import OmniDimension from "@omnidim-ai/sdk";

const omni = new OmniDimension({ apiKey: process.env.OMNIDIM_API_KEY! });

await omni.calls.dispatch({ agent_id: 123, to_number: "+15551234567" });
```

Same thing in Python:

```bash
pip install omnidimension
```

```python
import os

from omnidimension import Client

client = Client(api_key=os.environ["OMNIDIM_API_KEY"])

client.call.dispatch_call(agent_id=123, to_number="+15551234567")
```

Get a key at [omnidim.io/api-management](https://omnidim.io/api-management).

## Build agents from your editor

Connect any MCP client to your account and it can create agents, dispatch calls,
and read transcripts.

```bash
claude mcp add --transport http omnidim https://mcp.omnidim.io/mcp --scope user
```

For a local process instead, run `npx -y @omnidim-ai/mcp-server setup`.
[Per-client guides](https://docs.omnidim.io/docs/mcp).

## Repositories

| | |
| --- | --- |
| **Server SDKs** | [TypeScript](https://github.com/Omnidim/omnidim-typescript-sdk) · [Python](https://github.com/Omnidim/omnidim-python-sdk) |
| **Browser** | [`@omnidim-ai/client`](https://www.npmjs.com/package/@omnidim-ai/client) for in-page voice sessions ([guide](https://docs.omnidim.io/docs/sdks/web)) |
| **Model Context Protocol** | [Hosted server](https://github.com/Omnidim/omnidim-mcp-cloud) (OAuth, no install) · [Local stdio server](https://github.com/Omnidim/omnidim-mcp-server) |
| **Automation** | [n8n nodes](https://github.com/Omnidim/n8n-nodes-omnidimension) |
| **Examples** | [Omnidim/examples](https://github.com/Omnidim/examples) |
| **API spec** | [openapi.yaml](https://docs.omnidim.io/openapi.yaml) |

## Docs and help

- [Developer documentation](https://docs.omnidim.io/docs) and [tutorials](https://docs.omnidim.io/docs/tutorials)
- [Discord](https://discord.gg/kdjzykMTHJ) for questions and build help
- [Service status](https://status.omnidim.io)
- Bugs in an open repository go to that repository's issues. Anything else:
  [support@omnidim.io](mailto:support@omnidim.io)

## Contributing

Fixes, documentation improvements, and new examples are welcome. Read the
contributing guide in the repository you are changing, and please do not include
API keys, call recordings, or customer data in issues or pull requests. Report
security concerns privately to [support@omnidim.io](mailto:support@omnidim.io).
