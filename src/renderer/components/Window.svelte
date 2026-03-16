<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import OrbAvatar from './OrbAvatar.svelte';
  import AgentName from './AgentName.svelte';
  import Transcript from './Transcript.svelte';
  import InputBar from './InputBar.svelte';
  import ServiceCard from './ServiceCard.svelte';
  import Timer from './Timer.svelte';
  import Canvas from './Canvas.svelte';
  import Artefact from './Artefact.svelte';
  import Settings from './Settings.svelte';
  import SetupWizard from './SetupWizard.svelte';
  import MirrorSetup from './MirrorSetup.svelte';
  import SplashScreen from './SplashScreen.svelte';
  import ShutdownScreen from './ShutdownScreen.svelte';
  import { session } from '../stores/session.svelte';
  import { audio } from '../stores/audio.svelte';
  import { agents } from '../stores/agents.svelte';

  import { addMessage, completeLast, transcript } from '../stores/transcript.svelte';
  import { getArtifact } from '../stores/artifacts.svelte';

  import { api } from '../api';

  // Brain frames for update check screen - lazy loaded, only resolved when needed
  const brainFramePaths: string[] = [];
  const brainModules = import.meta.glob(
    '../../../resources/icons/brain_frames/brain_*.png',
    { eager: false, query: '?url', import: 'default' }
  );
  const brainModuleKeys = Object.keys(brainModules).sort();
  let brainFramesLoaded = false;
  async function ensureBrainFrames(): Promise<void> {
    if (brainFramesLoaded) return;
    for (const key of brainModuleKeys) {
      const mod = await brainModules[key]() as string;
      brainFramePaths.push(mod);
    }
    brainFramesLoaded = true;
  }
  let updateBrainFrame = $state(0);
  let updateBrainTimer: ReturnType<typeof setInterval> | null = null;

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  let showSettings = $state(false);
  let showTimer = $state(false);
  let showCanvas = $state(false);
  let showArtefact = $state(false);
  let needsSetup = $state(false);
  let mirrorSetupVisible = $state(false);

  // Update check phase (before splash)
  let updateCheckVisible = $state(true);
  let updateStatus = $state<'idle' | 'checking' | 'available' | 'downloading' | 'downloaded' | 'up-to-date' | 'error'>('idle');
  let updateVersion = $state('');
  let updatePercent = $state(0);

  // Boot decay animation (normal boot, not first launch)
  let bootDecayVisible = $state(false);
  let bootDecayFrame = $state(0);
  let bootDecayOpacity = $state(1);
  let bootDecayTimer: ReturnType<typeof setInterval> | null = null;

  // Splash screen
  let splashVisible = $state(false);
  let avatarDownloading = $state(false);
  let avatarDownloadPercent = $state(0);

  // Shutdown screen
  let shutdownVisible = $state(false);

  // Mode toggles
  let avatarVisible = $state(true);
  let isMuted = $state(false);
  let wakeListening = $state(false);
  let callActive = $state(false);
  let hasNewArtefacts = $state(false);

  // Eye mode - hides transcript when active
  let eyeMode = $state(false);

  // ---------------------------------------------------------------------------
  // Setup flow state (runs in main chat, not static screens)
  // ---------------------------------------------------------------------------

  /** Which overlay phase the wizard is in ('hidden' = chat is active) */
  let setupWizardPhase = $state<'welcome' | 'creating' | 'done' | 'hidden'>('hidden');
  /** Whether the setup flow is active (services + agent creation in main chat) */
  let setupActive = $state(false);
  /** Brief flag for InputBar enter animation after name submission */
  let setupJustEnteredChat = $state(false);
  /** Current service step: 0-4 = showing card, 5+ = services complete */
  let setupServiceStep = $state(0);
  /** Whether the service card is currently visible */
  let setupShowServiceCard = $state(false);
  /** Services that were saved */
  let setupServicesSaved: string[] = [];
  /** Services that were skipped */
  let setupServicesSkipped: string[] = [];
  /** Created agent display name (for creating/done overlays) */
  let setupCreatedAgentName = $state('');
  /** User name from welcome screen */
  let setupUserName = $state('');

  // Pre-baked opening paragraphs - streamed one at a time during setup
  const SETUP_PARAGRAPHS = [
    "I'm Xan. I ship with the system. Protector, first contact, always on.",
    "You already have me. But the real power is in creating something yours - a companion with its own edges, its own voice, someone shaped by you for a specific purpose.",
    "First, we need to connect some services. Let's get started.",
  ];

  // Paragraph streaming timing (ms between each paragraph appearing)
  const PARA_STREAM_DELAY = 3500;

  // Agent switch clip-path animation
  let agentSwitchActive = $state(false);
  let agentSwitchClip = $state('circle(0% at 50% 50%)');

  // Agent deferral (codec-style handoff)
  let deferralActive = $state(false);
  let deferralTarget = $state('');
  let deferralProgress = $state(0);

  // Ask-user dialog (MCP ask_user -> GUI)
  let askVisible = $state(false);
  let askQuestion = $state('');
  let askActionType = $state<'question' | 'confirmation' | 'permission' | 'secure_input'>('question');
  let askRequestId = $state('');
  let askReply = $state('');
  let askInputType = $state<'password' | 'email' | 'url' | 'number' | 'text'>('password');
  let askLabel = $state('');
  let askDestination = $state('');

  // Silence timer - prompts after configurable idle period
  let lastInputTime = $state(Date.now());
  let silencePromptVisible = $state(false);
  let silenceTimerId: ReturnType<typeof setTimeout> | null = null;
  let silenceTimerEnabled = true;
  let silenceTimeoutMs = 5 * 60 * 1000; // default 5 minutes

  // Pending bundle update banner
  let pendingUpdateVersion = $state<string | null>(null);

  // Status bar metrics
  let lastResponseMs = $state<number | null>(null);
  let contextUsagePercent = $state<number | null>(null);
  let inferenceStartTime = 0;

  // Track inference timing via session state changes
  $effect(() => {
    if (session.inferenceState === 'thinking') {
      inferenceStartTime = Date.now();
    } else if (session.inferenceState === 'idle' && inferenceStartTime > 0) {
      lastResponseMs = Date.now() - inferenceStartTime;
      inferenceStartTime = 0;
    }
  });

  // Journal nudge state - once per session
  let journalNudgeShown = $state(false);
  let journalNudgeVisible = $state(false);

  // ---------------------------------------------------------------------------
  // Boot sequence
  // ---------------------------------------------------------------------------

  let bootRan = false;

  /** Run update check - resolves when check is done (up-to-date, error, or downloaded) */
  async function runUpdateCheck(): Promise<void> {
    if (!api) return;

    // Load brain frames on demand (not at startup)
    await ensureBrainFrames();

    // Start brain frame cycling
    updateBrainFrame = 0;
    updateBrainTimer = setInterval(() => {
      if (brainFramePaths.length > 0) {
        updateBrainFrame = (updateBrainFrame + 1) % brainFramePaths.length;
      }
    }, 400);

    return new Promise<void>((resolve) => {
      let resolved = false;
      const done = () => {
        if (!resolved) {
          resolved = true;
          if (updateBrainTimer) { clearInterval(updateBrainTimer); updateBrainTimer = null; }
          resolve();
        }
      };

      // Timeout - don't block boot forever (4 seconds max)
      const timeout = setTimeout(done, 4000);

      api.onUpdateAvailable?.((info: { version: string }) => {
        updateStatus = 'available';
        updateVersion = info.version;
        api.downloadUpdate?.();
        updateStatus = 'downloading';
      });

      api.onUpdateNotAvailable?.(() => {
        updateStatus = 'up-to-date';
        clearTimeout(timeout);
        done();
      });

      api.onUpdateProgress?.((progress: { percent: number }) => {
        updateStatus = 'downloading';
        updatePercent = progress.percent;
      });

      api.onUpdateDownloaded?.((info: { version: string }) => {
        updateStatus = 'downloaded';
        updateVersion = info.version;
        clearTimeout(timeout);
        // Auto quit-and-install after brief pause
        setTimeout(() => {
          api.quitAndInstall?.();
        }, 1500);
        // Don't resolve - app is restarting
      });

      api.onUpdateError?.(() => {
        updateStatus = 'error';
        clearTimeout(timeout);
        done();
      });

      updateStatus = 'checking';
      api.checkForUpdates?.();
    });
  }

  async function runBootSequence() {
    if (bootRan) return;
    bootRan = true;

    if (!api) return; // Splash will dismiss itself after decay animation

    // Listen for avatar download events
    api.onAvatarDownloadStart?.(() => {
      avatarDownloading = true;
      avatarDownloadPercent = 0;
    });
    api.onAvatarDownloadProgress?.((data: { percent: number }) => {
      avatarDownloadPercent = data.percent;
    });
    api.onAvatarDownloadComplete?.(() => {
      avatarDownloading = false;
    });
    api.onAvatarDownloadError?.(() => {
      avatarDownloading = false;
    });

    // ── Update check phase (blocks before splash) ──
    await runUpdateCheck();
    updateCheckVisible = false;

    // Load config and agent list
    try {
      const [cfg, agentList] = await Promise.all([
        api.getConfig(),
        api.getAgents(),
      ]);
      agents.current = cfg.agentName || '';
      agents.displayName = cfg.agentDisplayName || cfg.agentName || '';
      agents.list = agentList || [];

      // Apply config-driven defaults
      if (cfg.eyeModeDefault) eyeMode = true;
      if (cfg.muteByDefault) { isMuted = true; api?.setMuted?.(true); }
      if (cfg.silenceTimerEnabled === false) silenceTimerEnabled = false;
      if (cfg.silenceTimerMinutes) silenceTimeoutMs = cfg.silenceTimerMinutes * 60 * 1000;
    } catch {
      // continue with defaults
    }

    // Check if setup needed
    try {
      needsSetup = await api.needsSetup();
    } catch {
      needsSetup = false;
    }

    if (needsSetup) {
      // First launch - show cinematic splash then welcome overlay
      splashVisible = true;
      setupWizardPhase = 'welcome';
    } else {
      // Normal boot - play brain decay animation while fetching opening line
      await ensureBrainFrames();
      bootDecayVisible = true;
      bootDecayFrame = 0;
      bootDecayOpacity = 1;

      const decayDone = new Promise<void>((resolve) => {
        bootDecayTimer = setInterval(() => {
          if (bootDecayFrame < brainFramePaths.length - 1) {
            bootDecayFrame++;
          } else {
            if (bootDecayTimer) { clearInterval(bootDecayTimer); bootDecayTimer = null; }
            // Hold on final frame briefly, then fade out
            setTimeout(() => {
              bootDecayOpacity = 0;
              setTimeout(() => {
                bootDecayVisible = false;
                resolve();
              }, 500);
            }, 300);
          }
        }, 200);
      });

      // Fetch opening line in parallel with the animation
      let opening: string | null = null;
      try {
        opening = await api.getOpeningLine();
      } catch {
        // use default
      }

      await decayDone;

      if (opening) {
        addMessage('agent', opening);
        completeLast();
      }
    }
    // Splash dismisses itself via onComplete when decay finishes + download done
  }

  // ---------------------------------------------------------------------------
  // Setup flow - runs in the main chat (Transcript + InputBar)
  // ---------------------------------------------------------------------------

  async function onSetupNameEntered(name: string) {
    setupUserName = name;
    if (api) await api.updateConfig({ USER_NAME: name });

    // Dismiss the welcome overlay - chat + ambient video visible
    setupWizardPhase = 'hidden';
    setupActive = true;

    // Stream paragraphs one at a time with delays
    api?.playAgentAudio?.('opening.mp3');

    let cumulativeText = '';
    for (let i = 0; i < SETUP_PARAGRAPHS.length; i++) {
      if (i > 0) {
        await new Promise(r => setTimeout(r, PARA_STREAM_DELAY));
      }
      cumulativeText += (cumulativeText ? '\n\n' : '') + SETUP_PARAGRAPHS[i];
      // Update the single agent message with growing text
      if (i === 0) {
        addMessage('agent', cumulativeText);
      } else {
        // Replace last message content with the growing text
        const msgs = transcript.messages;
        if (msgs.length > 0) {
          msgs[msgs.length - 1].content = cumulativeText;
          msgs[msgs.length - 1].revealed = cumulativeText.length;
        }
      }
    }
    completeLast();

    // Wait for last paragraph to settle, then show first service card
    await new Promise(r => setTimeout(r, 1500));
    setupServiceStep = 0;
    setupShowServiceCard = true;
  }

  // Service titles for chat messages (matches ServiceCard.SERVICE_PROMPTS order)
  const SETUP_SERVICE_TITLES = [
    'Voice - ElevenLabs',
    'Visual Presence - Fal.ai',
    'Messaging - Telegram',
    'Google Workspace + YouTube + Photos',
    'GitHub',
  ];

  // Narration text + pre-baked audio for each service transition
  const SETUP_NARRATIONS: Record<number, { text: string; audio: string }> = {
    1: { text: "Good. Now - your visual presence. Fal handles image and video generation for your avatar.", audio: 'narration_fal.mp3' },
    2: { text: "Messaging. This lets your companion reach you directly - check-ins, reminders, morning briefs.", audio: 'narration_telegram.mp3' },
    3: { text: "Google Workspace. Calendar, email, drive - if you use Google, this gives your companion eyes on your schedule.", audio: 'narration_google.mp3' },
    4: { text: "Last one. GitHub. Repos, issues, pull requests.", audio: 'narration_github.mp3' },
  };

  /** Stream narration text word-by-word into chat, with pre-baked audio playback */
  async function streamNarration(text: string, audioFile?: string): Promise<void> {
    addMessage('agent', '');
    const words = text.split(' ');
    const msgs = transcript.messages;

    if (audioFile) {
      // Play pre-baked audio in background while text streams
      api?.playAgentAudio?.(audioFile);

      // Stream words with timing that roughly matches speech cadence
      const msPerWord = 120; // ~150 wpm
      let accumulated = '';
      for (let i = 0; i < words.length; i++) {
        accumulated += (i > 0 ? ' ' : '') + words[i];
        if (msgs.length > 0) {
          msgs[msgs.length - 1].content = accumulated;
          msgs[msgs.length - 1].revealed = accumulated.length;
        }
        await new Promise(r => setTimeout(r, msPerWord));
      }

      // Estimate audio duration from file size (rough: ~10KB/s for mp3 speech)
      // Add small buffer after text finishes streaming
      await new Promise(r => setTimeout(r, 800));
    } else {
      // No audio - stream text quickly
      let accumulated = '';
      for (let i = 0; i < words.length; i++) {
        accumulated += (i > 0 ? ' ' : '') + words[i];
        if (msgs.length > 0) {
          msgs[msgs.length - 1].content = accumulated;
          msgs[msgs.length - 1].revealed = accumulated.length;
        }
        await new Promise(r => setTimeout(r, 40));
      }
      await new Promise(r => setTimeout(r, 600));
    }
    completeLast();
  }

  async function onSetupServiceSaved(key: string) {
    setupServicesSaved.push(key);

    // Show confirmation in chat
    const title = SETUP_SERVICE_TITLES[setupServiceStep] || key;
    addMessage('system', `${title} saved.`);
    completeLast();

    await advanceSetupService();
  }

  async function onSetupServiceSkipped(key: string) {
    setupServicesSkipped.push(key);

    // Show skip in chat
    const title = SETUP_SERVICE_TITLES[setupServiceStep] || key;
    addMessage('system', `${title} skipped.`);
    completeLast();

    await advanceSetupService();
  }

  async function advanceSetupService() {
    const nextStep = setupServiceStep + 1;
    const narration = SETUP_NARRATIONS[nextStep];

    setupServiceStep = nextStep;

    if (nextStep >= SETUP_SERVICE_TITLES.length) {
      // All services done
      setupShowServiceCard = false;

      // Health check - verify Claude CLI is reachable before proceeding
      try {
        const health = await api?.healthCheck?.();
        if (health && !health.ok) {
          addMessage('system',
            'Claude Code CLI not found. Install it with:\n\n' +
            '```\nnpm install -g @anthropic-ai/claude-code\n```\n\n' +
            'Then relaunch the app. Without it, your companion cannot think.'
          );
          completeLast();
          // Still allow proceeding - they might fix it later
        } else if (health?.hint) {
          addMessage('system', health.hint);
          completeLast();
        }
      } catch { /* non-fatal */ }

      const noVoiceKey = setupServicesSkipped.includes('ELEVENLABS_API_KEY');
      if (noVoiceKey) {
        // No ElevenLabs - play pre-baked farewell
        api?.playAgentAudio?.('voice_farewell.mp3');
        addMessage('agent',
          "System configured. This is the last you'll hear of my voice " +
          "until you add an ElevenLabs API key in Settings. Now - who " +
          "do you want to create?"
        );
        completeLast();
      } else {
        // Play pre-baked service complete audio
        await streamNarration('System configured. Now - who do you want to create?', 'service_complete.mp3');
      }

      // Trigger InputBar enter animation now that services are done
      setupJustEnteredChat = true;
      setTimeout(() => { setupJustEnteredChat = false; }, 800);
    } else if (narration) {
      // Hide card, stream narration with pre-baked audio, then show next card
      setupShowServiceCard = false;
      await streamNarration(narration.text, narration.audio);
      setupShowServiceCard = true;
    } else {
      setupShowServiceCard = true;
    }
  }

  /** Submit handler passed to InputBar during setup - routes to wizard inference */
  async function setupSubmit(text: string) {
    if (session.inferenceState === 'thinking') return; // prevent concurrent calls
    addMessage('user', text);
    completeLast();
    session.inferenceState = 'thinking';

    try {
      const response = await api.wizardInference(text);

      // Add agent response to the main transcript
      addMessage('agent', response);
      completeLast();

      // Check if the response contains AGENT_CONFIG JSON
      const configMatch = response.match(/```json\s*(\{[\s\S]*?"AGENT_CONFIG"[\s\S]*?\})\s*```/);
      if (configMatch) {
        try {
          const parsed = JSON.parse(configMatch[1]);
          const agentConfig = parsed.AGENT_CONFIG;
          if (agentConfig && agentConfig.display_name) {
            // Play farewell before switching (uses Xan's audio dir)
            api?.playAgentAudio?.('voice_farewell.mp3');

            // Show creating overlay
            setupCreatedAgentName = agentConfig.display_name;
            setupWizardPhase = 'creating';

            try {
              const manifest = await api.createAgent(agentConfig);
              if (manifest && manifest.name) {
                await api.switchAgent(manifest.name as string);
                agents.current = (manifest as Record<string, string>).name;
                agents.displayName = agentConfig.display_name;
              }

              // Brief pause on creating screen, then done
              setTimeout(() => {
                setupWizardPhase = 'done';
              }, 2500);
            } catch (createErr) {
              // Agent creation or switch failed - recover from creating overlay
              setupWizardPhase = 'hidden';
              addMessage('system', `Failed to create agent: ${createErr instanceof Error ? createErr.message : 'Unknown error'}. Try again.`);
              completeLast();
            }
          }
        } catch {
          // JSON parse failed - continue conversation
        }
      }
    } catch {
      addMessage('agent', 'Something went wrong. Try again.');
      completeLast();
    }

    session.inferenceState = 'idle';
  }

  function skipAgentCreation() {
    finishSetup();
  }

  async function finishSetup() {
    setupActive = false;
    needsSetup = false;
    setupWizardPhase = 'hidden';

    if (api) {
      const updates: Record<string, unknown> = {
        USER_NAME: setupUserName,
        setup_complete: true,
      };
      await api.updateConfig(updates);

      // Force config reload so avatar paths pick up newly downloaded assets
      await api.reloadConfig?.();

      // Reload config and agent list
      try {
        const [cfg, agentList] = await Promise.all([
          api.getConfig(),
          api.getAgents(),
        ]);
        agents.current = (cfg as Record<string, string>).agentName || '';
        agents.displayName = (cfg as Record<string, string>).agentDisplayName || (cfg as Record<string, string>).agentName || '';
        agents.list = (agentList as string[]) || [];

        // Fetch opening line for the (possibly new) agent
        const opening = await api.getOpeningLine();
        if (opening) {
          addMessage('agent', opening);
          completeLast();
        }
      } catch { /* continue with defaults */ }
    }
  }

  function onSetupWizardComplete() {
    finishSetup();
  }

  function onSplashComplete() {
    splashVisible = false;
    // Play "What is your name?" audio when welcome screen becomes visible
    if (needsSetup && setupWizardPhase === 'welcome') {
      api?.playAgentAudio?.('name.mp3');
    }
  }

  function onShutdownComplete() {
    // Tell main process to actually quit
    api?.requestShutdown?.();
  }

  function startShutdown() {
    if (shutdownVisible) return;
    shutdownVisible = true;
  }

  // ---------------------------------------------------------------------------
  // Silence timer
  // ---------------------------------------------------------------------------

  function resetSilenceTimer() {
    lastInputTime = Date.now();
    silencePromptVisible = false;

    if (silenceTimerId) clearTimeout(silenceTimerId);
    if (!silenceTimerEnabled || setupActive || needsSetup) return;
    silenceTimerId = setTimeout(() => {
      silencePromptVisible = true;
    }, silenceTimeoutMs);
  }

  function dismissSilencePrompt() {
    silencePromptVisible = false;
    resetSilenceTimer();
  }

  // ---------------------------------------------------------------------------
  // Agent switch animation
  // ---------------------------------------------------------------------------

  function playAgentSwitchAnimation() {
    // No-op - clip-path eye blink removed per user preference
  }

  // ---------------------------------------------------------------------------
  // Agent deferral (codec-style handoff)
  // ---------------------------------------------------------------------------

  async function handleDeferralRequest(data: { target: string; context: string; user_question: string }) {
    if (deferralActive || !api) return;

    deferralActive = true;
    deferralTarget = data.target;

    // Stop any ongoing inference
    if (api.stopInference) {
      api.stopInference();
    }

    // Kill audio
    if (api.stopPlayback) {
      api.stopPlayback();
    }

    // Iris wipe animation (fast, codec-style)
    deferralProgress = 0;
    requestAnimationFrame(() => {
      deferralProgress = 1;
    });

    // At peak black - switch agent
    setTimeout(async () => {
      try {
        const result = await api.completeDeferral(data);
        agents.current = result.agentName;
        agents.displayName = result.agentDisplayName;
        deferralTarget = '';
        
        // Iris open animation
        deferralProgress = 2;
        setTimeout(() => {
          deferralActive = false;
          deferralProgress = 0;
        }, 300);
      } catch (err) {
        console.error('[deferral] failed:', err);
        deferralActive = false;
        deferralProgress = 0;
      }
    }, 250);
  }

  // ---------------------------------------------------------------------------
  // Ask-user handlers
  // ---------------------------------------------------------------------------

  // Inline artifact card clicked in transcript - open in Artefact overlay
  function handleInlineArtifactClick(id: string) {
    const art = getArtifact(id);
    if (!art) return;
    // Load into the Artefact overlay by dispatching an artefact:updated-style event
    // The Artefact component listens on the 'artefact:updated' channel for content
    showArtefact = true;
    hasNewArtefacts = false;
    // Emit directly to the Artefact component via the IPC bus
    // The simplest approach: use the api.on listener that Artefact already has
    if (api) {
      // Synthesize an artefact:updated event via main process would be complex,
      // so instead we use a custom event on the window
      window.dispatchEvent(new CustomEvent('inline-artifact', {
        detail: { type: art.type, content: art.content, title: art.title },
      }));
    }
  }

  function resetAskState() {
    askVisible = false;
    askRequestId = '';
    askReply = '';
    askQuestion = '';
    askActionType = 'question';
    askInputType = 'password';
    askLabel = '';
    askDestination = '';
  }

  function handleAskConfirm(approved: boolean) {
    if (!askRequestId || !api) return;
    api.respondToAsk(askRequestId, approved);
    resetAskState();
  }

  function handleAskReply() {
    if (!askRequestId || !api) return;
    const text = askReply.trim();
    if (!text) return;
    api.respondToAsk(askRequestId, text);
    resetAskState();
  }

  function handleAskDismiss() {
    if (!askRequestId || !api) return;
    api.respondToAsk(askRequestId, null);
    resetAskState();
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  let agentSwitchCleanup: (() => void) | null = null;
  const ipcCleanups: (() => void)[] = [];

  onMount(() => {
    runBootSequence().then(() => resetSilenceTimer());

    // Listen for deferral requests from main process
    if (api && typeof api.on === 'function') {
      ipcCleanups.push(api.on('deferral:request', handleDeferralRequest));

      // Listen for ask-user requests from MCP
      ipcCleanups.push(api.on('ask:request', (data: { question: string; action_type: string; request_id: string; input_type?: string; label?: string; destination?: string }) => {
        askQuestion = data.question;
        askActionType = (data.action_type || 'question') as typeof askActionType;
        askRequestId = data.request_id;
        askReply = '';
        askInputType = (data.input_type as typeof askInputType) || 'password';
        askLabel = data.label || '';
        askDestination = data.destination || '';
        askVisible = true;
      }));

      // Auto-show canvas when content is written (even if Canvas not mounted yet)
      ipcCleanups.push(api.on('canvas:updated', () => {
        showCanvas = true;
      }));

      // Auto-show artefact overlay when MCP creates one
      ipcCleanups.push(api.on('artefact:updated', () => {
        showArtefact = true;
        hasNewArtefacts = true;
      }));

      // Show badge when artefact is generating
      ipcCleanups.push(api.on('artefact:loading', () => {
        hasNewArtefacts = true;
      }));

      // Context usage updates from main process
      ipcCleanups.push(api.on('inference:contextUsage', (percent: number) => {
        contextUsagePercent = percent;
      }));

      // Journal nudge from main process (silence-based)
      ipcCleanups.push(api.on('journal:nudge', () => {
        if (!journalNudgeShown) {
          journalNudgeVisible = true;
          journalNudgeShown = true;
        }
      }));
    }

    // Listen for bundle update ready
    if (api?.onBundleReady) {
      const bundleCleanup = api.onBundleReady((info: { version: string }) => {
        pendingUpdateVersion = info.version;
      });
      if (bundleCleanup) ipcCleanups.push(bundleCleanup);
    }
    // Check for previously downloaded bundle update
    api?.getBundleStatus?.().then((status) => {
      if (status?.pending?.pendingRestart && status.pending.version) {
        pendingUpdateVersion = status.pending.version;
      }
    }).catch(() => { /* non-critical */ });

    // Listen for shutdown signal from main process
    const shutdownCleanup = api?.onShutdownRequested?.(() => {
      startShutdown();
    });
    if (shutdownCleanup) ipcCleanups.push(shutdownCleanup);
  });

  onDestroy(() => {
    if (bootDecayTimer) clearInterval(bootDecayTimer);
    if (silenceTimerId) clearTimeout(silenceTimerId);
    if (agentSwitchCleanup) agentSwitchCleanup();
    ipcCleanups.forEach((fn) => fn());
    // Clean up wake word audio
    try { wakeProcessor?.disconnect(); } catch { /* already disconnected */ }
    wakeProcessor = null;
    try { wakeAudioCtx?.close(); } catch { /* already closed */ }
    wakeAudioCtx = null;
    if (wakeStream) { wakeStream.getTracks().forEach((t) => t.stop()); wakeStream = null; }
    // Clean up call audio
    try { callProcessor?.disconnect(); } catch { /* already disconnected */ }
    callProcessor = null;
    try { callAudioCtx?.close(); } catch { /* already closed */ }
    callAudioCtx = null;
    if (callStream) { callStream.getTracks().forEach((t) => t.stop()); callStream = null; }
  });

  // ---------------------------------------------------------------------------
  // Agent cycling
  // ---------------------------------------------------------------------------

  async function cycleAgent(direction: number) {
    const list = agents.list;
    if (list.length < 2) return;
    const idx = list.indexOf(agents.current);
    const next = list[(idx + direction + list.length) % list.length];
    agents.switchDirection = direction;
    if (api) {
      const result = await api.switchAgent(next);
      agents.current = result.agentName;
      agents.displayName = result.agentDisplayName;
      playAgentSwitchAnimation();

      // Check if the new agent needs custom setup
      if (result.customSetup === 'mirror') {
        mirrorSetupVisible = true;
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Mode button actions
  // ---------------------------------------------------------------------------

  function toggleAvatar() { avatarVisible = !avatarVisible; }

  function toggleMute() {
    isMuted = !isMuted;
    api?.setMuted?.(isMuted);
  }

  // Wake word audio capture state
  let wakeStream: MediaStream | null = null;
  let wakeAudioCtx: AudioContext | null = null;
  let wakeProcessor: ScriptProcessorNode | null = null;

  let wakeStarting = false;
  async function toggleWake() {
    if (wakeStarting) return;

    if (!wakeListening && api) {
      wakeStarting = true;
      wakeListening = true;
      try {
        wakeStream = await navigator.mediaDevices.getUserMedia({
          audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true },
        });
        wakeAudioCtx = new AudioContext({ sampleRate: 16000 });
        const source = wakeAudioCtx.createMediaStreamSource(wakeStream);
        wakeProcessor = wakeAudioCtx.createScriptProcessor(4096, 1, 1);
        wakeProcessor.onaudioprocess = (e: AudioProcessingEvent) => {
          if (!wakeListening) return;
          const data = e.inputBuffer.getChannelData(0);
          api.sendWakeWordChunk(data.buffer.slice(0));
        };
        source.connect(wakeProcessor);
        wakeProcessor.connect(wakeAudioCtx.destination);
      } catch (err) {
        console.error('[wake word] failed to start audio capture:', err);
        wakeListening = false;
      } finally {
        wakeStarting = false;
      }
    } else {
      wakeListening = false;
      // Tear down ambient audio capture
      if (wakeProcessor) { wakeProcessor.disconnect(); wakeProcessor = null; }
      if (wakeAudioCtx) { wakeAudioCtx.close(); wakeAudioCtx = null; }
      if (wakeStream) { wakeStream.getTracks().forEach((t) => t.stop()); wakeStream = null; }
    }
  }

  // Voice call mode - continuous record/transcribe/send/TTS loop
  let callStream: MediaStream | null = null;
  let callAudioCtx: AudioContext | null = null;
  let callProcessor: ScriptProcessorNode | null = null;
  let callChunks: Float32Array[] = [];
  let callSilentFrames = 0;
  let callSpeechStarted = false;
  const CALL_ENERGY_THRESHOLD = 0.015;
  const CALL_SILENCE_FRAMES = 15; // ~15 * 4096/16000 = ~3.8s of silence
  const CALL_MIN_CHUNKS = 4; // minimum chunks before processing

  let callStarting = false;
  async function toggleCall() {
    if (callStarting) return;

    if (!callActive && api) {
      callStarting = true;
      callActive = true;
      try {
        callStream = await navigator.mediaDevices.getUserMedia({
          audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true },
        });
        callAudioCtx = new AudioContext({ sampleRate: 16000 });
        const source = callAudioCtx.createMediaStreamSource(callStream);
        callProcessor = callAudioCtx.createScriptProcessor(4096, 1, 1);
        callChunks = [];
        callSilentFrames = 0;
        callSpeechStarted = false;

        callProcessor.onaudioprocess = (e: AudioProcessingEvent) => {
          if (!callActive) return;
          const data = e.inputBuffer.getChannelData(0);
          const chunk = new Float32Array(data);

          // Calculate RMS energy
          let sum = 0;
          for (let i = 0; i < chunk.length; i++) sum += chunk[i] * chunk[i];
          const energy = Math.sqrt(sum / chunk.length);

          if (energy > CALL_ENERGY_THRESHOLD) {
            callSpeechStarted = true;
            callSilentFrames = 0;
            callChunks.push(chunk);
          } else if (callSpeechStarted) {
            callSilentFrames++;
            callChunks.push(chunk);
            if (callSilentFrames >= CALL_SILENCE_FRAMES && callChunks.length >= CALL_MIN_CHUNKS) {
              // Utterance complete - send accumulated audio for transcription
              const allChunks = callChunks;
              callChunks = [];
              callSpeechStarted = false;
              callSilentFrames = 0;
              processCallUtterance(allChunks);
            }
          }
        };
        source.connect(callProcessor);
        callProcessor.connect(callAudioCtx.destination);
      } catch (err) {
        console.error('[call] failed to start:', err);
        callActive = false;
      } finally {
        callStarting = false;
      }
    } else {
      callActive = false;
      // Tear down call audio
      if (callProcessor) { callProcessor.disconnect(); callProcessor = null; }
      if (callAudioCtx) { callAudioCtx.close(); callAudioCtx = null; }
      if (callStream) { callStream.getTracks().forEach((t) => t.stop()); callStream = null; }
      callChunks = [];
    }
  }

  async function processCallUtterance(chunks: Float32Array[]) {
    if (!api) return;
    // Concatenate chunks into a single buffer and send for STT
    const totalLen = chunks.reduce((acc, c) => acc + c.length, 0);
    const merged = new Float32Array(totalLen);
    let offset = 0;
    for (const c of chunks) {
      merged.set(c, offset);
      offset += c.length;
    }
    // Use the existing audio:chunk -> audio:stop flow for transcription
    api.sendAudioChunk(merged.buffer.slice(0));
    try {
      const transcript = await api.stopRecording();
      if (transcript && transcript.trim().length > 1) {
        addMessage('user', transcript.trim());
        completeLast();
        await api.sendMessage(transcript.trim());
      }
    } catch {
      // Transcription failed - continue listening
    }
  }

  // ---------------------------------------------------------------------------
  // Keyboard shortcuts
  // ---------------------------------------------------------------------------

  function onKeydown(e: KeyboardEvent) {
    // Reset silence timer on any keypress
    resetSilenceTimer();

    // Cmd+Up/Down: cycle agents
    if (e.metaKey && e.key === 'ArrowUp') {
      e.preventDefault();
      cycleAgent(-1);
    } else if (e.metaKey && e.key === 'ArrowDown') {
      e.preventDefault();
      cycleAgent(1);
    }
    // Cmd+, : settings
    else if (e.metaKey && e.key === ',') {
      e.preventDefault();
      showSettings = !showSettings;
    }
    // Cmd+K : canvas
    else if (e.metaKey && e.key === 'k') {
      e.preventDefault();
      showCanvas = !showCanvas;
    }
    // Cmd+E : toggle eye mode (hide transcript)
    else if (e.metaKey && e.key === 'e') {
      e.preventDefault();
      eyeMode = !eyeMode;
    }
    // Cmd+Shift+W : wake word
    else if (e.metaKey && e.shiftKey && e.key === 'W') {
      e.preventDefault();
      toggleWake();
    }
    // Cmd+Shift+C : copy last agent message to clipboard
    else if (e.metaKey && e.shiftKey && e.key === 'C') {
      e.preventDefault();
      copyLastAgentMessage();
    }
    // Cmd+Shift+T : toggle timer overlay
    else if (e.metaKey && e.shiftKey && e.key === 'T') {
      e.preventDefault();
      showTimer = !showTimer;
    }
    // Cmd+Shift+A : toggle always-on-top
    else if (e.metaKey && e.shiftKey && e.key === 'A') {
      e.preventDefault();
      api?.toggleAlwaysOnTop?.();
    }
    // Escape: close overlays in priority order
    else if (e.key === 'Escape') {
      if (showSettings) showSettings = false;
      else if (showArtefact) showArtefact = false;
      else if (showCanvas) showCanvas = false;
      else if (showTimer) showTimer = false;
      else if (silencePromptVisible) dismissSilencePrompt();
    }
  }

  /** Copy the most recent agent message text to the clipboard. */
  function copyLastAgentMessage() {
    const msgs = transcript.messages;
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].role === 'agent' && msgs[i].content.trim()) {
        navigator.clipboard.writeText(msgs[i].content).catch(() => {});
        return;
      }
    }
  }

  // Also reset silence timer on mouse movement
  function onMouseMove() {
    resetSilenceTimer();
  }
</script>

<svelte:window onkeydown={onKeydown} onmousemove={onMouseMove} />

<div class="window">
  <!-- Background orb / avatar layer -->
  {#if avatarVisible}
    <OrbAvatar pip={showArtefact} ambientMode={updateCheckVisible || bootDecayVisible || splashVisible || setupActive} />
  {/if}

  <!-- Warm vignette overlay (shows during audio playback) -->
  <div
    class="vignette"
    style="opacity: {audio.vignetteOpacity}"
  ></div>

  <!-- Update check phase (before splash) -->
  {#if updateCheckVisible}
    <div class="update-check-overlay">
      <div class="update-check-content">
        {#if brainFramePaths[updateBrainFrame]}
          <img
            class="update-brain"
            src={brainFramePaths[updateBrainFrame]}
            alt=""
            draggable="false"
          />
        {/if}
        {#if updateStatus === 'checking'}
          <span class="update-label">Checking for updates...</span>
        {:else if updateStatus === 'downloading'}
          <div class="update-progress-bar">
            <div class="update-progress-fill" style="width: {updatePercent}%"></div>
          </div>
          <span class="update-label">Downloading {updateVersion}... {Math.round(updatePercent)}%</span>
        {:else if updateStatus === 'downloaded'}
          <span class="update-label">Installing update...</span>
        {:else if updateStatus === 'up-to-date'}
          <span class="update-label">Up to date</span>
        {:else if updateStatus === 'error'}
          <span class="update-label"></span>
        {/if}
      </div>
    </div>
  {/if}

  <!-- Boot decay animation (normal boot) -->
  {#if bootDecayVisible}
    <div class="boot-decay-overlay" style="opacity: {bootDecayOpacity}">
      <div class="boot-decay-content">
        {#if brainFramePaths[bootDecayFrame]}
          <img
            class="update-brain"
            src={brainFramePaths[bootDecayFrame]}
            alt=""
            draggable="false"
          />
        {/if}
      </div>
    </div>
  {/if}

  <!-- Splash screen - cinematic intro + download progress -->
  {#if splashVisible}
    <SplashScreen
      downloading={avatarDownloading}
      downloadPercent={avatarDownloadPercent}
      onComplete={onSplashComplete}
    />
  {/if}

  <!-- Shutdown screen - reverse brain decay -->
  {#if shutdownVisible}
    <ShutdownScreen onComplete={onShutdownComplete} />
  {/if}

  <!-- Agent switch clip-path reveal animation -->
  {#if agentSwitchActive}
    <div
      class="agent-switch-overlay"
      style="clip-path: {agentSwitchClip}"
    ></div>
  {/if}

  <!-- Agent deferral iris wipe (codec-style handoff) -->
  {#if deferralActive}
    <div
      class="deferral-overlay"
      style="
        clip-path: circle(
          {deferralProgress === 0 ? '150%' : deferralProgress === 1 ? '0%' : '150%'}
          at 50% 50%
        )
      "
    >
      {#if deferralProgress === 1}
        <span class="deferral-label">Handing off to {deferralTarget}...</span>
      {/if}
    </div>
  {/if}

  <!-- Ask-user dialog (MCP ask_user) -->
  {#if askVisible}
    <div class="ask-overlay" data-no-drag>
      <div class="ask-dialog">
        <div class="ask-icon">
          {#if askActionType === 'secure_input'}&#x1f512;{:else if askActionType === 'question'}?{:else}&#x1f512;{/if}
        </div>
        <p class="ask-question">{askQuestion}</p>

        {#if askActionType === 'confirmation' || askActionType === 'permission'}
          <div class="ask-buttons">
            <button class="ask-btn ask-btn-no" onclick={() => handleAskConfirm(false)}>No</button>
            <button class="ask-btn ask-btn-yes" onclick={() => handleAskConfirm(true)}>Yes</button>
          </div>
        {:else if askActionType === 'secure_input'}
          <div class="ask-input-row">
            <input
              type={askInputType}
              class="ask-input"
              placeholder={askLabel || 'Enter value...'}
              bind:value={askReply}
              onkeydown={(e: KeyboardEvent) => { if (e.key === 'Enter') handleAskReply(); }}
              autocomplete="off"
              spellcheck="false"
            />
            <button class="ask-btn ask-btn-yes" onclick={handleAskReply}>Save</button>
          </div>
          {#if askDestination}
            <p class="ask-destination-note">Value will be saved securely</p>
          {/if}
        {:else}
          <div class="ask-input-row">
            <input
              type="text"
              class="ask-input"
              placeholder="Type your reply..."
              bind:value={askReply}
              onkeydown={(e: KeyboardEvent) => { if (e.key === 'Enter') handleAskReply(); }}
            />
            <button class="ask-btn ask-btn-yes" onclick={handleAskReply}>Send</button>
          </div>
        {/if}

        <button class="ask-dismiss" onclick={handleAskDismiss}>Dismiss</button>
      </div>
    </div>
  {/if}

  <!-- Top bar: agent name - hidden only during update check -->
  <div class="top-bar" class:hidden={updateCheckVisible}>
    <AgentName
      name={agents.displayName}
      direction={agents.switchDirection}
      canCycle={agents.list.length > 1}
      onCycleUp={() => cycleAgent(-1)}
      onCycleDown={() => cycleAgent(1)}
    />
  </div>

  <!-- Mode buttons (top-right) - hidden only during update check -->
  <div class="mode-buttons" class:hidden={updateCheckVisible} data-no-drag>
    <!-- Eye: toggle avatar -->
    <button
      class="mode-btn"
      class:active={!avatarVisible}
      onclick={toggleAvatar}
      title="Toggle avatar"
      aria-label="Toggle avatar"
    >
      {#if avatarVisible}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
          <circle cx="12" cy="12" r="3"/>
        </svg>
      {:else}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
          <line x1="1" y1="1" x2="23" y2="23"/>
        </svg>
      {/if}
    </button>

    <!-- Mute: toggle TTS -->
    <button
      class="mode-btn"
      class:active={isMuted}
      onclick={toggleMute}
      title="Mute / unmute voice"
      aria-label="Toggle mute"
    >
      {#if isMuted}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
          <line x1="23" y1="9" x2="17" y2="15"/>
          <line x1="17" y1="9" x2="23" y2="15"/>
        </svg>
      {:else}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
          <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/>
        </svg>
      {/if}
    </button>

    <!-- Wake word -->
    <button
      class="mode-btn"
      class:wake-active={wakeListening}
      onclick={toggleWake}
      title="Wake word listening"
      aria-label="Toggle wake word"
    >
      {#if wakeListening}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
          <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
          <line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/>
        </svg>
      {:else}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <line x1="1" y1="1" x2="23" y2="23"/>
          <path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6"/>
          <path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2c0 .76-.13 1.49-.36 2.18"/>
          <line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/>
        </svg>
      {/if}
    </button>

    <!-- Call (voice) -->
    <button
      class="mode-btn"
      class:active={callActive}
      onclick={toggleCall}
      title="Voice call"
      aria-label="Voice call"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
        <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/>
      </svg>
    </button>

    <!-- Artefact -->
    <button
      class="mode-btn artefact-btn"
      onclick={() => showArtefact = !showArtefact}
      title="Artefacts"
      aria-label="Artefacts"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="16" y1="13" x2="8" y2="13"/>
        <line x1="16" y1="17" x2="8" y2="17"/>
      </svg>
      {#if hasNewArtefacts}
        <span class="artefact-badge"></span>
      {/if}
    </button>

    <!-- Timer -->
    <button class="mode-btn" onclick={() => showTimer = !showTimer} title="Timer" aria-label="Timer">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
        <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
      </svg>
    </button>

    <!-- Minimize -->
    <button
      class="mode-btn"
      onclick={() => api?.minimizeWindow()}
      title="Minimize"
      aria-label="Minimize"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
        <line x1="5" y1="12" x2="19" y2="12"/>
      </svg>
    </button>

    <!-- Settings -->
    <button
      class="mode-btn"
      class:active={showSettings}
      onclick={() => showSettings = !showSettings}
      title="Settings"
      aria-label="Settings"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
        <circle cx="12" cy="12" r="3"/>
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
      </svg>
    </button>
  </div>

  <!-- Update banner -->
  {#if pendingUpdateVersion}
    <div class="update-banner">
      <span class="update-banner-text">Update v{pendingUpdateVersion} ready</span>
      <button class="update-banner-btn" onclick={() => api?.restartForUpdate()}>Restart to update</button>
    </div>
  {/if}

  <!-- Chat area - hidden in eye mode -->
  {#if !eyeMode}
    <Transcript onArtifactClick={handleInlineArtifactClick} />
  {/if}

  <!-- Service card (setup flow - appears between transcript and input bar) -->
  {#if setupShowServiceCard}
    <ServiceCard
      step={setupServiceStep}
      onSaved={onSetupServiceSaved}
      onSkipped={onSetupServiceSkipped}
    />
  {/if}

  <!-- Input bar - hidden during splash, welcome, and setup service phase -->
  {#if !(setupWizardPhase === 'welcome' || splashVisible || (setupActive && setupServiceStep < SETUP_SERVICE_TITLES.length))}
    <InputBar
      onSubmit={setupActive && setupServiceStep >= SETUP_SERVICE_TITLES.length ? setupSubmit : undefined}
      placeholder={setupActive && setupServiceStep >= SETUP_SERVICE_TITLES.length ? 'Describe who you want to create...' : undefined}
      enterAnimation={setupActive && setupJustEnteredChat}
    />
  {/if}

  <!-- Skip agent creation (visible during AI creation phase of setup) -->
  {#if setupActive && !setupShowServiceCard && setupServiceStep >= 4}
    <button class="skip-creation-btn" onclick={skipAgentCreation}>
      Skip agent creation
    </button>
  {/if}

  <!-- Silence prompt - subtle nudge after 5 minutes idle -->
  {#if silencePromptVisible}
    <button class="silence-prompt" onclick={dismissSilencePrompt}>
      <span class="silence-text">Still here?</span>
    </button>
  {/if}

  <!-- Overlays (conditionally rendered) -->
  {#if showTimer}
    <Timer onClose={() => showTimer = false} />
  {/if}

  {#if showCanvas}
    <Canvas onClose={() => showCanvas = false} onRequestShow={() => showCanvas = true} />
  {/if}

  {#if showArtefact}
    <Artefact onClose={() => showArtefact = false} />
  {/if}

  {#if showSettings}
    <Settings onClose={() => showSettings = false} />
  {/if}

  <!-- Setup wizard overlays (welcome / creating / done) -->
  {#if setupWizardPhase !== 'hidden'}
    <SetupWizard
      phase={setupWizardPhase}
      createdAgentName={setupCreatedAgentName}
      onNameEntered={onSetupNameEntered}
      onComplete={onSetupWizardComplete}
    />
  {/if}

  <!-- Mirror custom setup (shown when switching to Mirror for the first time) -->
  {#if mirrorSetupVisible}
    <MirrorSetup onComplete={() => { mirrorSetupVisible = false; }} />
  {/if}

  <!-- Status bar - response time and context usage -->
  {#if lastResponseMs !== null || contextUsagePercent !== null}
    <div class="status-bar">
      {#if lastResponseMs !== null}
        <span class="status-metric">{lastResponseMs}ms</span>
      {/if}
      {#if contextUsagePercent !== null}
        <span class="status-metric">ctx {contextUsagePercent}%</span>
      {/if}
    </div>
  {/if}

  <!-- Journal nudge - gentle suggestion after silence -->
  {#if journalNudgeVisible}
    <button class="journal-nudge" onclick={() => { journalNudgeVisible = false; }}>
      <span class="journal-nudge-text">been a while - want to write something down?</span>
    </button>
  {/if}
</div>

<style>
  .window {
    position: relative;
    width: 100%;
    height: 100%;
    overflow: hidden;
    background: var(--bg);
    display: flex;
    flex-direction: column;
  }

  .vignette {
    position: absolute;
    inset: 0;
    pointer-events: none;
    z-index: 1;
    background: radial-gradient(
      ellipse at center,
      transparent 30%,
      rgba(40, 25, 10, 0.47) 100%
    );
    transition: opacity 0.8s ease;
  }

  /* -- Agent switch clip-path overlay -- */

  .agent-switch-overlay {
    position: absolute;
    inset: 0;
    z-index: 75;
    background: var(--bg);
    pointer-events: none;
    transition: clip-path 0.65s cubic-bezier(0.4, 0, 0.2, 1);
  }

  /* -- Agent deferral iris wipe (codec-style handoff) -- */

  .deferral-overlay {
    position: absolute;
    inset: 0;
    z-index: 80;
    background: #000;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: clip-path 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  }

  .deferral-label {
    font-family: var(--font-sans);
    font-size: 14px;
    color: var(--text-secondary);
    letter-spacing: 0.5px;
    opacity: 0.7;
  }

  /* -- Silence prompt -- */

  .silence-prompt {
    position: absolute;
    bottom: 90px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 12;
    cursor: pointer;
    animation: silenceFadeIn 1.5s ease forwards;
  }

  .silence-text {
    font-family: var(--font-sans);
    font-size: 13px;
    color: var(--text-dim);
    letter-spacing: 1px;
    opacity: 0.6;
    transition: opacity 0.3s;
  }

  .silence-prompt:hover .silence-text {
    opacity: 1;
  }

  @keyframes silenceFadeIn {
    from { opacity: 0; transform: translateX(-50%) translateY(6px); }
    to { opacity: 1; transform: translateX(-50%) translateY(0); }
  }

  /* -- Top bar -- */

  .top-bar {
    position: relative;
    z-index: 10;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: var(--pad);
    padding-top: 36px;
    padding-bottom: 0;
    transition: opacity 0.5s ease;
  }

  .top-bar.hidden {
    opacity: 0;
    pointer-events: none;
  }

  /* -- Update banner -- */

  .update-banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 16px;
    background: rgba(100, 140, 255, 0.1);
    border-bottom: 1px solid rgba(100, 140, 255, 0.15);
    flex-shrink: 0;
  }

  .update-banner-text {
    color: var(--text-secondary);
    font-size: 12px;
    font-family: var(--font-sans);
  }

  .update-banner-btn {
    background: rgba(100, 140, 255, 0.2);
    border: 1px solid rgba(100, 140, 255, 0.3);
    color: rgba(100, 140, 255, 0.9);
    font-size: 11px;
    font-family: var(--font-sans);
    padding: 4px 12px;
    border-radius: 6px;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
  }

  .update-banner-btn:hover {
    background: rgba(100, 140, 255, 0.3);
    border-color: rgba(100, 140, 255, 0.5);
  }

  /* -- Mode buttons -- */

  .mode-buttons {
    position: absolute;
    top: 14px;
    right: var(--pad);
    z-index: 15;
    display: flex;
    flex-direction: row;
    gap: 2px;
    transition: opacity 0.5s ease;
  }

  .mode-buttons.hidden {
    opacity: 0;
    pointer-events: none;
  }

  .mode-btn {
    width: var(--button-size);
    height: var(--button-size);
    border: none;
    background: transparent;
    color: var(--text-dim);
    border-radius: 8px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: color 0.2s, background 0.2s;
    position: relative;
  }

  .mode-btn:hover {
    color: var(--text-secondary);
    background: rgba(255, 255, 255, 0.04);
  }

  .mode-btn.active {
    color: var(--text-primary);
    background: rgba(40, 40, 50, 0.82);
  }

  .mode-btn.wake-active {
    color: rgba(120, 255, 140, 0.9);
    background: rgba(30, 80, 40, 0.82);
  }

  /* Artefact badge */
  .artefact-badge {
    position: absolute;
    top: 6px;
    right: 6px;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: rgba(100, 180, 255, 0.88);
  }

  /* -- Skip agent creation (setup flow) -- */

  .skip-creation-btn {
    align-self: center;
    padding: 6px 16px;
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text-dim);
    font-family: var(--font-sans);
    font-size: 12px;
    cursor: pointer;
    margin-bottom: 8px;
    transition: color 0.15s, border-color 0.15s;
    flex-shrink: 0;
    z-index: 10;
  }

  .skip-creation-btn:hover {
    color: var(--text-secondary);
    border-color: var(--text-dim);
  }

  /* -- Ask-user dialog -- */

  .ask-overlay {
    position: absolute;
    inset: 0;
    z-index: 70;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(8px);
    animation: askFadeIn 0.2s ease;
  }

  @keyframes askFadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
  }

  .ask-dialog {
    background: rgba(20, 20, 24, 0.95);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 28px 24px 20px;
    max-width: 360px;
    width: 90%;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 16px;
  }

  .ask-icon {
    font-size: 28px;
    width: 48px;
    height: 48px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(255, 255, 255, 0.06);
    border-radius: 50%;
    color: var(--text-secondary);
    font-weight: 600;
  }

  .ask-question {
    font-family: var(--font-sans);
    font-size: 14px;
    line-height: 1.5;
    color: var(--text-primary);
    text-align: center;
    margin: 0;
  }

  .ask-buttons {
    display: flex;
    gap: 12px;
    width: 100%;
  }

  .ask-btn {
    flex: 1;
    padding: 10px 16px;
    border: 1px solid var(--border);
    border-radius: 10px;
    font-family: var(--font-sans);
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
  }

  .ask-btn-yes {
    background: rgba(100, 180, 120, 0.2);
    color: #8fd4a0;
    border-color: rgba(100, 180, 120, 0.3);
  }

  .ask-btn-yes:hover {
    background: rgba(100, 180, 120, 0.35);
    border-color: rgba(100, 180, 120, 0.5);
  }

  .ask-btn-no {
    background: rgba(200, 80, 80, 0.15);
    color: #d08888;
    border-color: rgba(200, 80, 80, 0.25);
  }

  .ask-btn-no:hover {
    background: rgba(200, 80, 80, 0.3);
    border-color: rgba(200, 80, 80, 0.45);
  }

  .ask-input-row {
    display: flex;
    gap: 8px;
    width: 100%;
  }

  .ask-input {
    flex: 1;
    padding: 10px 12px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid var(--border);
    border-radius: 10px;
    color: var(--text-primary);
    font-family: var(--font-sans);
    font-size: 13px;
    outline: none;
    transition: border-color 0.15s;
  }

  .ask-input:focus {
    border-color: rgba(255, 255, 255, 0.25);
  }

  .ask-input::placeholder {
    color: var(--text-dim);
  }

  .ask-destination-note {
    font-size: 11px;
    color: var(--text-dim);
    margin: 4px 0 0;
    font-style: italic;
  }

  .ask-dismiss {
    background: none;
    border: none;
    color: var(--text-dim);
    font-family: var(--font-sans);
    font-size: 11px;
    cursor: pointer;
    padding: 4px 8px;
    transition: color 0.15s;
  }

  .ask-dismiss:hover {
    color: var(--text-secondary);
  }

  /* -- Status bar -- */

  .status-bar {
    position: absolute;
    bottom: 4px;
    right: 12px;
    z-index: 8;
    display: flex;
    gap: 12px;
    pointer-events: none;
    opacity: 0.35;
    transition: opacity 0.3s;
  }

  .status-bar:hover {
    opacity: 0.6;
  }

  .status-metric {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--text-dim);
    letter-spacing: 0.5px;
  }

  /* -- Journal nudge -- */

  .journal-nudge {
    position: absolute;
    bottom: 90px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 12;
    cursor: pointer;
    background: none;
    border: none;
    padding: 0;
    animation: silenceFadeIn 1.5s ease forwards;
  }

  .journal-nudge-text {
    font-family: var(--font-sans);
    font-size: 13px;
    color: var(--text-dim);
    letter-spacing: 0.5px;
    opacity: 0.5;
    transition: opacity 0.3s;
  }

  .journal-nudge:hover .journal-nudge-text {
    opacity: 0.9;
  }

  /* ── Boot decay overlay (normal boot) ── */
  .boot-decay-overlay {
    position: fixed;
    inset: 0;
    z-index: 10000;
    background: #000;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: opacity 0.5s ease;
  }

  .boot-decay-content {
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  /* ── Update check overlay ── */
  .update-check-overlay {
    position: fixed;
    inset: 0;
    z-index: 10000;
    background: #000;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .update-check-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 16px;
  }

  .update-brain {
    width: 56px;
    height: 56px;
    object-fit: contain;
    user-select: none;
    -webkit-user-drag: none;
  }

  .update-label {
    font-family: var(--font-sans);
    font-size: 12px;
    letter-spacing: 1px;
    color: rgba(255, 255, 255, 0.3);
    text-transform: lowercase;
  }

  .update-progress-bar {
    width: 200px;
    height: 2px;
    background: rgba(255, 255, 255, 0.08);
    border-radius: 1px;
    overflow: hidden;
  }

  .update-progress-fill {
    height: 100%;
    background: rgba(100, 140, 255, 0.5);
    transition: width 0.3s ease;
  }
</style>

