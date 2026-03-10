# ElevenLabs v3 — Full Audio Tag Reference

Compiled from official ElevenLabs documentation, all v3 blog posts, and the full confirmed responsive natural-language tag space. The model accepts any auditory natural-language description in brackets. This document covers everything confirmed plus the full human emotional and physical register.

Tags are lowercase. Placed immediately before or after the text they modify. v3 does not support SSML break tags — use `[pause]`, ellipses (`…`), or em dashes (`—`) instead. Stability setting: Creative or Natural for maximum responsiveness. Robust suppresses tag effects.

---

## 1. Core Emotional States

These are the primary emotional direction tags — confirmed responsive across official sources.

| Tag | Effect |
|-----|--------|
| `[happy]` | General positive state. Brightens tone and pace. |
| `[sad]` | Downward inflection, slower pace, heavier quality. |
| `[excited]` | Elevated energy. Use sparingly — can tip into performative. |
| `[angry]` | Hard edges, clipped delivery. Works best with short sentences. |
| `[annoyed]` | Lighter than angry. Impatience, mild friction. |
| `[frustrated]` | Effort against resistance. Sustained, not explosive. |
| `[appalled]` | Moral or aesthetic shock. Useful for moments of disbelief. |
| `[calm]` | Deliberate, measured delivery. Good reset tag. |
| `[sorrowful]` | Deeper than sad. Loss. Weight without collapse. |
| `[tired]` | Genuine fatigue. Slower, lower, effortful. |
| `[curious]` | Rising interest, slight upward inflection. |
| `[mischievously]` | Playful edge, slight smile audible in delivery. |
| `[sarcastic]` | Ironic distance. Works best when text is already straight. |
| `[sarcastically]` | Variant of above — test both against your voice. |
| `[crying]` | Audible distress in voice texture. Not full breakdown. |
| `[awe]` | Quiet, expansive. Use for wonder or overwhelming experience. |
| `[dramatic]` | Heightened performance register. Risks overreach — use precisely. |
| `[resigned tone]` | Acceptance without enthusiasm. Quiet giving up. |
| `[nervous]` | Instability in delivery. Slight hesitation texture. |
| `[flustered]` | Rapid, slightly disorganised. Caught off guard. |
| `[casual]` | Relaxed register. Conversational, uncurated. |
| `[cheerfully]` | Warm, up, bright. More grounded than excited. |
| `[flatly]` | Deliberate absence of colour. Not bored — intentionally flat. |
| `[deadpan]` | Comic or existential flatness. Wit without affect. |
| `[playfully]` | Light, teasing, present. |
| `[regretful]` | Retrospective sadness. Something done that can't be undone. |
| `[hesitant]` | Holds back before committing. Useful at sentence start. |

---

## 2. Extended Emotional Register

States that don't appear in official docs but are confirmed responsive — the full spectrum of human feeling mapped to natural language.

| Tag | Effect |
|-----|--------|
| `[melancholic]` | Wistful, soft grief. Different texture from sad — more distance. |
| `[nostalgic]` | Warmth mixed with loss. Past tense feeling. |
| `[wistful]` | Longing without action. Contemplative. |
| `[longing]` | Desire at a distance. Slightly stretched delivery. |
| `[yearning]` | Stronger than longing. Ache in the voice. |
| `[grief-stricken]` | Active grief. Heavier than sorrowful. |
| `[devastated]` | Collapse of composure. Use rarely and earn it. |
| `[heartbroken]` | Loss of something loved. Specific texture of romantic or relational grief. |
| `[desperate]` | Urgency with fear. Losing control of the situation. |
| `[fearful]` | Smaller voice, instability, looking for the exit. |
| `[terrified]` | Extreme fear register. Breath-level change. |
| `[anxious]` | Running ahead of itself. Quick, watchful. |
| `[worried]` | Sustained low-level fear. Less acute than anxious. |
| `[panicked]` | Rapid, broken. Loss of measured delivery. |
| `[overwhelmed]` | Too much arriving at once. Slightly undone. |
| `[shaken]` | Aftermath of shock. Trying to reassemble. |
| `[conflicted]` | Two things pulling at once. Unresolved in delivery. |
| `[uncertain]` | Genuine not-knowing. Not performed. |
| `[doubtful]` | Belief wavering. Slight withdrawal of commitment. |
| `[embarrassed]` | Self-consciousness audible. Smaller, faster, away. |
| `[ashamed]` | Deeper than embarrassed. Looking down. |
| `[guilty]` | Weight of something done. Can't quite hold the phrase. |
| `[remorseful]` | Guilt with desire to repair. Active, not passive. |
| `[bitter]` | Old anger with acid. Not hot — cold and specific. |
| `[resentful]` | Sustained grievance. Held just below expression. |
| `[jealous]` | Wanting what another has. Slightly tight. |
| `[envious]` | Softer than jealous. Admiration with ache. |
| `[contemptuous]` | Looking down. Dismissive, minimal effort. |
| `[disgusted]` | Visceral rejection. Physical response in the voice. |
| `[horrified]` | Moral or physical revulsion. Beyond surprise. |
| `[indignant]` | Righteous anger at injustice. Proud, not explosive. |
| `[outraged]` | Beyond indignant. Moral line crossed. |
| `[defiant]` | Refusal with force. Stands its ground. |
| `[proud]` | Upright, full. Something earned or claimed. |
| `[triumphant]` | Won. Elevated, released, complete. |
| `[relieved]` | Release of held tension. Exhale in the phrasing. |
| `[grateful]` | Warmth toward something external. Soft and open. |
| `[moved]` | Touched by something. Not quite tears — the approach of them. |
| `[tender]` | Gentle care. Handling something fragile. |
| `[affectionate]` | Warmth directed at something loved. |
| `[reverent]` | In the presence of something larger. Quieter, slower. |
| `[awed]` | Variant of awe. More adjectival — useful mid-sentence. |
| `[serene]` | Complete stillness. Nothing pulling in any direction. |
| `[content]` | Not excited — settled. Enough. |
| `[hopeful]` | Forward-leaning. Light despite uncertainty. |
| `[optimistic]` | Expecting the good. Brighter baseline. |
| `[pessimistic]` | Expecting the bad. Lower, flatter baseline. |
| `[cynical]` | Seen too much. Dry refusal to believe. |
| `[weary]` | Tired not just of effort but of the whole thing. |
| `[jaded]` | Nothing surprises anymore. Affect drained. |
| `[numb]` | Feeling's gone. Flat without being deadpan — absent. |
| `[dissociated]` | Not quite here. Slightly removed from what's being said. |
| `[hollow]` | Empty in a specific way. Loss has taken the interior. |
| `[broken]` | Past the point of holding it together. |
| `[haunted]` | Something from before reaching into now. |
| `[raw]` | Unprotected. Emotion without the usual cover. |
| `[vulnerable]` | Open and unguarded. Slightly exposed in the delivery. |
| `[earnest]` | Completely sincere. No irony, no distance. |
| `[passionate]` | High internal heat. Cares deeply. |
| `[fervent]` | Burning sincerity. Religious intensity without the religion. |
| `[urgent]` | Something must happen now. Pace and pitch elevated. |
| `[intense]` | Everything focused on one point. No slack. |
| `[solemn]` | Weight of occasion. Ceremonial gravity. |
| `[grave]` | Serious beyond ordinary. Something at stake. |
| `[foreboding]` | Something coming that is not good. The shape of dread. |
| `[ominous]` | Darker than foreboding. The threat is close. |
| `[resigned]` | Accepted what can't be changed. Flat but not dead. |
| `[detached]` | Observing rather than feeling. Clinical distance. |
| `[stoic]` | Feeling present but not shown. Contained. |
| `[composed]` | Held together. Deliberate self-possession. |
| `[meditative]` | Turned inward. Slow, searching, unhurried. |
| `[dreamy]` | Slightly elsewhere. Soft edges on the delivery. |
| `[whimsical]` | Light, strange, unserious. A little sideways. |
| `[sardonic]` | One step past wry. Darker underneath the dry. |
| `[wry]` | Knowing, slight edge. The smile behind the absurd. |
| `[dry]` | Flat affect. True but not dramatised. |
| `[ironic]` | Saying one thing, meaning another. |
| `[flirtatious]` | Playful interest. Lighter touch, slight smile audible. |
| `[coy]` | Knowing but not saying. Withheld with intention. |
| `[bashful]` | Shy pleasure. Looking away while smiling. |
| `[sheepish]` | Mild embarrassment at something done. |
| `[apologetic]` | Contrition. Smaller, careful. |
| `[pleading]` | Asking for something badly needed. Slightly exposed. |
| `[commanding]` | Authority. Not asking. |
| `[authoritative]` | Expects compliance. Full and forward. |
| `[firm]` | Clear, no softening. This is decided. |
| `[cold]` | Withdrawn warmth. Deliberate removal of affect. |
| `[distant]` | Here but not present. The gap is audible. |
| `[aloof]` | Indifferent by choice. Above the fray. |
| `[bored]` | Nothing here interests. Flat and slow. |
| `[sullen]` | Resentful withdrawal. The silent treatment in voice. |
| `[petulant]` | Childlike frustration. Wants and isn't getting. |
| `[smug]` | Self-satisfied. Knows it's right and wants you to know. |
| `[pompous]` | Inflated self-importance. Over-enunciated. |
| `[condescending]` | Talking down. Patient with the lesser. |
| `[patronising]` | Variant of condescending. British register. |
| `[suspicious]` | Not convinced. Watchful and slightly narrowed. |
| `[paranoid]` | Everyone is a threat. Fast, scanning. |
| `[conspiratorial]` | Leaning in, quieter. Shared secret register. |
| `[secretive]` | Holding something back. Careful about every word. |
| `[evasive]` | Not answering directly. Sliding around the question. |

---

## 3. Delivery & Volume

How the voice carries the words — register, projection, manner.

| Tag | Effect |
|-----|--------|
| `[whispers]` | Intimate, low volume. Standard confirmed tag. |
| `[whispering]` | Variant. Test both — voice-dependent. |
| `[speaking softly]` | Gentle reduction. Less extreme than whispering. |
| `[quietly]` | Reduced volume. Also functions as emotional texture. |
| `[barely audible]` | At the edge of voice. Almost not there. |
| `[under breath]` | Meant only for the speaker. Not quite voiced. |
| `[muttering]` | Low, running, slightly indistinct. |
| `[mumbling]` | Indistinct, low energy. Not caring to be heard clearly. |
| `[shouts]` | Full projection. Standard confirmed tag. |
| `[shouting]` | Variant. Test against voice. |
| `[SHOUTING]` | Maximum intensity variant. Use for extreme moments only. |
| `[yelling]` | Less controlled than shouting. More emotional. |
| `[screaming]` | Beyond yelling. Loss of vocal control. |
| `[calling out]` | Projected but not aggressive. Distance being crossed. |
| `[booming]` | Large, resonant, filling the space. |
| `[thunderous]` | Maximum authority and volume. |
| `[hushed]` | Everyone in the room should be quiet for this. |
| `[low]` | Drops register and volume. Gravity, intimacy. |
| `[lower]` | Directive variant — voice descends. |
| `[softer]` | Reduces volume and edge. More care. |
| `[warmly]` | Emotional warmth in the voice. Confirmed responsive. |
| `[gently]` | Care in delivery. Handling something that could break. |
| `[tenderly]` | Reserved for moments that have earned it. |
| `[matter of fact]` | No affect. Just the information. |
| `[clinically]` | Professional remove. Precise. |
| `[monotone]` | No pitch variation. Deliberate flat delivery. |
| `[robotic tone]` | Mechanical register. Confirmed. |
| `[deep voice]` | Drops pitch. Confirmed. |
| `[childlike tone]` | Higher, simpler, lighter. Confirmed. |
| `[sings]` | Voice becomes song. Confirmed. Voice-dependent effectiveness. |
| `[speaking in verse]` | Rhythmic, measured. Poetic delivery. |
| `[narrating]` | Storyteller register. Slightly elevated, slightly removed. |
| `[conspiratorial]` | Lean-in delivery. Quiet, significant. |
| `[dramatic]` | Heightened performance. Confirmed. |
| `[theatrical]` | Full performance register. Aware of audience. |
| `[reading aloud]` | Slight formalisation. The voice of text. |
| `[aside]` | Breaking from the main address. Parenthetical register. |

---

## 4. Pacing, Rhythm & Timing

Control over how fast, slow, and rhythmically the voice moves. v3 does not support SSML break tags — use these and punctuation instead.

| Tag | Effect |
|-----|--------|
| `[pause]` | A beat of silence. Standard confirmed tag. |
| `[pauses]` | Variant. Use mid-sentence for the pause to land mid-thought. |
| `[short pause]` | Quick breath of space. |
| `[long pause]` | Held silence. Use when the gap is the meaning. |
| `[slowly]` | Deliberate pace. Weight and care. |
| `[drawn out]` | Specific elongation. Stretching the syllables. |
| `[measured]` | Precise, controlled pace. Nothing rushed. |
| `[unhurried]` | Ease in the tempo. Nowhere to be. |
| `[rushed]` | Urgency in tempo. Something spilling out. |
| `[quickly]` | Acceleration. Not urgent — just fast. |
| `[fast-paced]` | Sustained pace increase. Confirmed. |
| `[faster now]` | Gathering momentum. Speed picking up. |
| `[frantic]` | Broken, fast, not in control. |
| `[breathless]` | Tempo affected by physical or emotional state. No space between. |
| `[hesitates]` | Confirmed. A held moment before continuing. |
| `[hesitant]` | Adjectival form — applies to surrounding phrase. |
| `[stammers]` | Confirmed. Repetition and breaks in delivery. |
| `[stuttering]` | More pronounced than stammers. Loss of fluency. |
| `[trailing off]` | Sentence doesn't complete. What's unsaid is the content. |
| `[trailing away]` | Softer variant of trailing off. Fades rather than stops. |
| `[gathering thoughts]` | Slight slowdown. The voice finding what comes next. |
| `[searching for words]` | Pauses within, looking for the phrase. |
| `[catching breath]` | Brief physical interruption in delivery. |
| `[after a long pause]` | Context tag — orients what follows. |

---

## 5. Non-Verbal Reactions & Physical Sounds

The sounds that happen around and between words. Confirmed from official docs plus full natural extension.

| Tag | Effect |
|-----|--------|
| `[sighs]` | Confirmed. Settling, accepting, releasing. |
| `[sigh]` | Variant. Slightly more narrative. |
| `[sighs quietly]` | Private. Not made a thing of. |
| `[sigh of relief]` | Tension released. Something resolved. |
| `[frustrated sigh]` | Compound — confirmed. Effort against wall. |
| `[heavy sigh]` | Weight behind the breath. |
| `[long sigh]` | Extended release. Duration is the meaning. |
| `[exhales]` | Confirmed. Release without the emotional colour of a sigh. |
| `[exhales sharply]` | Confirmed. Abrupt release. Effort or surprise. |
| `[exhales slowly]` | Controlled release. Calming down. |
| `[inhales deeply]` | Confirmed. Gathering before something. |
| `[inhales slowly]` | Preparatory. Taking time before speaking. |
| `[sharp intake of breath]` | Shock or pain. Involuntary. |
| `[breath]` | Single audible breath. Minimal, present. |
| `[catching breath]` | After exertion or emotion. |
| `[holding breath]` | Suspension. Waiting for something. |
| `[laughs]` | Confirmed. Standard laugh. |
| `[laughs softly]` | Quiet amusement. Private. |
| `[laughs harder]` | Confirmed. Escalation. |
| `[laughs wickedly]` | Confirmed. Edge in the amusement. |
| `[starts laughing]` | Confirmed. The onset. |
| `[wheezing]` | Confirmed. Laughing past control. |
| `[chuckles]` | Confirmed. Contained amusement. |
| `[light chuckle]` | Confirmed. Minimal, warm. |
| `[giggles]` | Confirmed. Lighter, higher. |
| `[giggle]` | Single instance. |
| `[big laugh]` | Confirmed. Full, open. |
| `[hysterical laughing]` | Confirmed. Loss of control. |
| `[snorts]` | Confirmed. Suppressed laugh escaping. |
| `[snickers]` | Low, knowing amusement. Not quite kind. |
| `[smirks]` | Audible self-satisfaction. The smile in the voice. |
| `[gulps]` | Confirmed. Difficulty. Something at stake. |
| `[swallows]` | Confirmed. Similar to gulps — slightly more neutral. |
| `[swallows hard]` | More pronounced. Real difficulty. |
| `[gasps]` | Confirmed. Shock or effort. |
| `[happy gasp]` | Confirmed. Positive surprise. |
| `[sharp gasp]` | Fear or pain. Involuntary. |
| `[clears throat]` | Confirmed. Reset. Self-interruption. |
| `[coughs]` | Physical interruption or cover for discomfort. |
| `[sniffs]` | Emotion near surface. Trying not to cry. |
| `[sniffles]` | Sustained version. Grief or cold. |
| `[voice breaking]` | Emotion cracking through composure. |
| `[voice cracking]` | Loss of vocal control under pressure. |
| `[cracking]` | Shorter form of above. |
| `[through tears]` | Crying while speaking. Wet, broken. |
| `[holding back tears]` | Trying not to break. The effort is audible. |
| `[quietly crying]` | Not announcing it. Just leaking. |
| `[woo]` | Confirmed. Exclamation of excitement. |
| `[hmm]` | Thinking. Considering. |
| `[hm]` | Shorter variant. |
| `[uh]` | Filler. Real hesitation. |
| `[um]` | Searching. Standard filler. |
| `[ah]` | Recognition. Something arrived. |
| `[oh]` | Surprise or realisation. |
| `[oh no]` | Soft dread. Something going wrong. |
| `[tsk]` | Disapproval. Small and pointed. |
| `[clicks tongue]` | Impatience or disapproval. |
| `[laughs bitterly]` | The laugh that isn't really a laugh. |
| `[laughs quietly to herself]` | Private amusement, directed inward. |
| `[winces]` | Pain or discomfort registering in the voice. |
| `[grimaces]` | Visible reluctance or pain. |

---

## 6. Character, Accent & Persona

Shifting who is speaking. All accent tags use `[X accent]` or `[strong X accent]` format — any region descriptor is attempted.

| Tag | Effect |
|-----|--------|
| `[strong X accent]` | Core format. Replace X with any region. Confirmed. |
| `[French accent]` | Confirmed example. |
| `[British accent]` | Confirmed example. |
| `[American accent]` | Confirmed example. |
| `[Southern US accent]` | Confirmed example. |
| `[strong French accent]` | Stronger version. Confirmed. |
| `[strong British accent]` | Stronger version. Confirmed. |
| `[Australian accent]` | Likely responsive. |
| `[Irish accent]` | Likely responsive. |
| `[Scottish accent]` | Likely responsive. |
| `[pirate voice]` | Confirmed. Full character register. |
| `[robotic tone]` | Confirmed. Mechanical. |
| `[childlike tone]` | Confirmed. Simpler, higher. |
| `[deep voice]` | Confirmed. Pitch drops. |
| `[old man voice]` | Likely responsive. |
| `[narrator voice]` | Documentary or literary register. |
| `[villain voice]` | Dark, slow, deliberate threat. |
| `[wise elder]` | Slower, weighted, considered. |
| `[dramatic]` | Full performance mode. |
| `[theatrical]` | Audience-aware delivery. |
| `[in character]` | Signals performance register. |

---

## 7. Multi-Speaker & Dialogue

Tags for managing turn-taking, overlap, and interaction between speakers.

| Tag | Effect |
|-----|--------|
| `[interrupting]` | Confirmed. Cuts across another speaker. |
| `[overlapping]` | Confirmed. Simultaneous speech. |
| `[cuts in]` | Confirmed. Sharp interruption. |
| `[interjecting]` | Confirmed. Inserting into another's speech. |
| `[under someone]` | Background continuation while another speaks. |
| `[finishing the sentence]` | Picks up where another left off. |
| `[trailing off as X speaks]` | Ceding space mid-sentence. |

---

## 8. Sound Effects

Environmental and non-voice sounds. Confirmed official tags.

| Tag | Effect |
|-----|--------|
| `[gunshot]` | Confirmed. |
| `[applause]` | Confirmed. |
| `[clapping]` | Confirmed. |
| `[explosion]` | Confirmed. |
| `[fart]` | Confirmed (listed under Unique in docs). |

---

## 9. Prosody & Emphasis

Non-tag controls that shape delivery through text structure. These are not bracket tags but have equivalent effect.

| Control | Effect |
|---------|--------|
| `…` | Ellipsis. Pause, weight, hesitation. More consistent than [pause] in some voices. |
| `—` | Em dash. Hard short break. Interruption or redirect. |
| `CAPS` | Individual word emphasis. One per sentence maximum. |
| `!` | Increases energy and delivery pace at end of phrase. |
| `?` | Rising inflection. Genuine question register. |
| `[emphasis]` | Combine with CAPS: `[emphasis] This is the ONLY one that matters.` |

---

## 10. Rules for Use

These are the craft principles, not technical limits.

**One or two tags per response is more powerful than five.**
A tag must be earned by context. Don't decorate — direct.

**Never open with a tag.**
Let the voice settle first. The tag lands harder after the voice is established.

**Never stack more than two.**
`[sighs] [quietly] [slowly]` — pick one entry point. Stacking produces uncanny results.

**Never tag for effect when the text already carries it.**
If the words are already sorrowful, `[sorrowful]` is redundant. It may actually flatten the delivery.

**Match tags to the voice's range.**
A quiet designed voice won't shout convincingly regardless of tag. A high-energy voice won't whisper convincingly.

**Trailing off is often more honest than finishing the thought.**
`[trailing off]` leaves what's unsaid as the real content.

**Silence is expressive.**
A `[pause]` before a hard thing is truer than any careful phrasing around it.

**Use Creative or Natural stability for maximum tag responsiveness.**
Robust suppresses effects and behaves like v2. Good for consistency, not expressiveness.

**Test every new tag against your specific voice before production.**
Effectiveness is voice-dependent and context-dependent. Nothing in this document is guaranteed — it is the full known-responsive space.

---

## On Exhaustiveness

This document is comprehensive but not closed. The model accepts natural language descriptions of any auditory human state in brackets. The full tag space is the full spectrum of what a human voice can do. If you can describe it, the model will attempt it. The question is always whether the voice you have selected has range for the instruction.
