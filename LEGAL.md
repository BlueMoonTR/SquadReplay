# Legal Notice — Data Protection and Liability

This notice is for anyone who runs the SquadReplay agent on their own Squad
server. Read it before installing. **Installing the agent means you accept
the obligations set out below.**

This document is not legal advice. Consult a lawyer about your own
situation.

## 1. Roles: the server owner is the data controller

SquadReplay is a tool. The **server owner who installs the agent** decides
which server it runs on, whose data it collects, which variant (read,
write, voice) is installed, and for what purpose the data is used.

Under the EU General Data Protection Regulation (GDPR) and Turkey's Law on
the Protection of Personal Data No. 6698 (KVKK):

- **Data controller:** the server owner / community that installs the
  agent.
- **SquadReplay:** the tool provider that processes, hosts and displays
  the data on the server owner's behalf and on their instructions.

**The server owner is responsible for the lawful processing of their
players' personal data.** SquadReplay is not liable for any claim, fine,
administrative sanction or damage arising from a server owner's failure
to meet the obligations below. If such a claim is brought against
SquadReplay, the server owner agrees to hold SquadReplay harmless from it.

## 2. What data is processed

The agent reads match data from the game server process's memory:

- the player's in-game name and clan tag,
- player identifiers (Epic Online Services ID; SteamID64 obtained over
  RCON on the central side),
- position, team, squad, role, health, vehicle and weapon use,
- kill, wound and damage events, match and player statistics,
- in-game chat and player join/leave events,
- **voice variants only:** players' in-game voice chat and the identity
  of the speaker.

This data is processed for match replays, the live map, statistics and
leaderboards, and is stored on the SquadReplay central server. Replays
are deleted when the community's storage quota or retention period is
reached; voice recordings are deleted together with the replay they
belong to.

## 3. The server owner's obligations

Before installing the agent, and for as long as it runs, the server owner
must:

1. **Inform players** (GDPR Art. 13, KVKK Art. 10): tell every player who
   joins the server, **before any data is collected**, that their data is
   recorded, for what purpose, where it is stored and what their rights
   are. A template is provided below. The notice must be easy to find —
   for example in the server name or message of the day, the community's
   Discord rules and its website.
2. **Have a lawful basis, and consent where required:** determine the
   lawful basis for the processing and obtain **explicit consent** where
   the law requires it. **Recording voice chat requires players' explicit
   consent.** Making sure that the voice of a player who has not consented
   is not recorded is the server owner's responsibility.
3. **Handle data subject requests** (GDPR Arts. 15–22, KVKK Art. 11):
   receive and answer players' requests for access, rectification and
   erasure. The server owner may ask SquadReplay for help with technical
   steps they cannot carry out themselves.
4. **Registration and international transfers:** meet any registration
   duty that applies to them (e.g. VERBİS in Turkey) and the rules on
   transferring personal data abroad (GDPR Chapter V, KVKK Art. 9).
5. **Limit access:** grant voice, player identifiers and admin-panel
   permissions only to staff who actually need them (the permissions
   table in the admin panel exists for this).
6. **Respect the game's licence:** comply with the game publisher's
   server licensing terms when operating the server.

## 4. Voice variants

The voice variants are enabled only for communities that declare to
SquadReplay that they meet these obligations. That declaration is the
server owner's responsibility; SquadReplay is not obliged to verify it.
SquadReplay may disable voice access if the declaration turns out to be
untrue.

## 5. No warranty

The software is provided "as is"; section 4 of the [LICENSE](LICENSE)
applies. SquadReplay does not warrant that the software is uninterrupted,
error-free or fit for a particular purpose. To the fullest extent
permitted by applicable law, SquadReplay is not liable for any direct or
indirect damage arising from its use.

## 6. Player notice template

Fill in the bracketed parts and publish it where players will see it
before they join.

> **[SERVER / COMMUNITY NAME] — Privacy Notice**
>
> Matches played on this server are recorded using SquadReplay. The data
> controller is **[COMMUNITY OR PERSON NAME]** (contact: **[EMAIL /
> DISCORD]**).
>
> **What is recorded:** your in-game name and clan tag, your player ID
> (EOS / SteamID), your in-match position, role, vehicle and weapon use,
> your kill and damage events, your in-game chat messages and your match
> statistics. **[If voice is recorded:]** your in-game voice chat.
>
> **Why:** to let players and staff watch match replays, to run the
> server and review rule violations, and to produce player statistics and
> leaderboards.
>
> **How long:** match recordings are deleted after **[PERIOD]**.
>
> **Your rights:** you can ask whether your data is processed, and
> request access to it, its correction or its erasure, by contacting
> **[CONTACT]**.
>
> **[If voice is recorded:]** If you do not consent to your voice chat
> being recorded, **[HOW TO OPT OUT / HOW CONSENT IS COLLECTED]**.
