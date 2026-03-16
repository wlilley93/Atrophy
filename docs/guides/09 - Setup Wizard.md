# Setup Wizard

The setup wizard runs on first launch. It walks you through naming yourself, connecting services, and creating your first agent - all inside a conversation with Xan, the built-in setup guide.

---

## What Happens

### 1. Welcome

You see the Atrophy logo and a single question: "What is your name, human?" Type your name and press Enter. This is how your agents will address you.

### 2. Xan Introduces Himself

Xan's opening message appears in the chat. If you've connected a voice service, you'll hear it spoken aloud.

### 3. Service Setup

Four service cards appear one at a time. Each has a **Save** and **Skip** button - nothing is required. Skip anything you don't want.

| Service | What It Does | Cost |
|---------|-------------|------|
| **ElevenLabs** | Gives your agents a voice (text-to-speech) | $5+/month |
| **Fal.ai** | Visual generation capabilities | Pay-as-you-go |
| **Telegram** | Lets agents message you outside the app | Free |
| **Google** | Gmail, Calendar, Drive, YouTube, Photos access via MCP | Free |

Each card verifies your credentials before saving. If verification fails, you'll see what went wrong.

### 4. Agent Creation

After services, Xan asks who you want to create. Describe the agent you want - a strategist, a journal companion, a fictional character, anything. Xan will ask 3-5 follow-up questions to flesh out the personality, then build the agent for you.

You can also click **Skip agent creation** to keep Xan as your default agent.

### 5. Done

Your new agent is created and ready. The wizard finishes and you're dropped into your first real conversation.

---

## Services in Detail

### ElevenLabs (Voice)

Paste your API key from [elevenlabs.io](https://elevenlabs.io). The app verifies it immediately. Once saved, your agents can speak. Without it, the app is text-only.

### Fal.ai (Visual)

Paste your API key from [fal.ai](https://fal.ai). Enables image generation capabilities for agents that support it.

### Telegram

The wizard walks you through the full Telegram setup:

1. **Create a bot** via [@BotFather](https://t.me/BotFather) on Telegram and paste the bot token
2. **Create a group** and enable Topics (Forum mode) in group settings
3. **Add the bot** to the group as an admin
4. **Create one topic per agent** - each agent gets its own topic thread

The wizard captures the bot token and the group ID (`TELEGRAM_GROUP_ID`). Each agent sends and receives messages in its own topic, so conversations stay cleanly separated - no routing logic needed. This replaces the previous flat-chat model where all agents shared a single chat and a router decided who should respond.

### Google

Click "Connect" and authorize in your browser. No Google Cloud setup needed - OAuth credentials are bundled. This gives agents access to your Gmail, Calendar, and Drive through MCP tools.

---

## Skipping

Everything in the wizard is skippable. Skip a service and the app works without it. Skip agent creation and Xan remains your default agent. You can always add services later in Settings.

---

## Re-running the Wizard

Two ways:

1. **Settings** > **App** section > **Reset Setup** - the wizard runs again on next launch
2. **Manual** - set `"setup_complete": false` in `~/.atrophy/config.json`

Resetting does not delete existing agents or their data. The wizard creates a new agent alongside any existing ones.
