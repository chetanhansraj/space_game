# Lunar Ark city builder: Tranquility

A city builder on one mare site near the Apollo 11 landing site. You build the base by hand
(power, the first habitat, oxygen, water, greenhouses, landing pad, rovers, gardens, clinic) and
zone land for Habitat, Industry and Commercial. Graders drive out and level zoned ground, then
settlers, companies and traders build and expand on it themselves where demand, habitability and
life support allow. Rovers find ore deposits that make Industry land worth more. As the town grows
its people expect more and cost more to supply, nations and companies bring contracts argued for
and against by the crew, and after the first sunrise things go wrong: solar storms, pressure
breaches, late shuttles, dust. Every night has to be survived on stored power.

## Where this sits

This folder is the city builder, a separate game from the trade economy in the rest of this
repository. Today it is a single-player prototype that runs entirely in the browser and keeps its
save in the player's own storage. It does not touch the trade game's ledger, clock or server, so
the invariants in the root `CLAUDE.md` (server authority, integer credits, one shared clock) do
not yet apply to it. They will apply to anything that links the two. The simulation is already
written for that day: it is pure, holds only tile coordinates, and changes state only through
`apply(state, intent)`.

Live at https://sim.lunarark.com. See `docs/DEPLOY.md`.

## Run it

    npm install
    npm run build      # writes dist/index.html and dist/game.js
    npm run dev        # rebuilds on change and serves dist/ locally
    npm test           # headless balance check, no browser needed
    npm run check      # TypeScript type check

## Layout

    src/sim/buildings.ts   Building catalogue. Pure data, keyed to Codex systems.
    src/sim/sim.ts         The simulation. No DOM, no graphics. State in, intents in, ticks out.
    src/sim/missions.ts    What the crew asks for, in order, with rewards.
    src/sim/contracts.ts   Offers from nations and companies, their terms, deadlines and penalties.
    src/sim/world.ts       Graders that level zoned ground, survey finds, and events.
    src/ui/advisor.ts      Urgent advice in the voice of the crew member whose job it is.
    src/view/view.ts       2D isometric renderer (PixiJS). Reads state, never changes it.
    src/view/pixi.ts       PixiJS is loaded from a CDN as a global; this re-exports it with types.
    src/ui/hud.ts          Resource strip, crew rail with chat-style messages, drawers, build categories, Moon clock, inspector, dialogs.
    src/main.ts            Game loop and input. Turns clicks into intents.
    test/bot.ts            Plays the game without graphics to prove the balance.

## The rules that keep 3D and multiplayer open

1. The simulation stores tile coordinates, never pixels.
2. Buildings are data. Art is looked up by building id in the view.
3. Every change goes through `apply(state, intent)`. Today the browser calls it.
   In the shared world the server calls it and broadcasts the result.
4. The state is plain JSON, so it can be saved, sent over a socket, or stored in a database.

## Tuning

All balance numbers live in `src/sim/buildings.ts` and the constants at the top of
`src/sim/sim.ts`. After changing them, run `npm test`. A test player who only does what the crew asks must bring all four
crew through the first night, then grow the base to a Colony within three lunar days without losing anyone.

## Known limits of this milestone

- Art is grey-box: flat-shaded prisms with two-letter labels.
- Codex references are system level (L1) and provisional.
- One site type and one level. Growth is fast and credits still pile up late; pacing needs tuning with real play.
- The name Tranquility is a working title.
