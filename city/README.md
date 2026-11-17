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

This folder is the city builder, and since `docs/DECISIONS.md` D69 it is the game. One source
makes two builds.

**The live town**, `npm run build:live`, served at `play.lunarark.com/town/`. The rules in
`src/sim/` are bundled by `npm run build:engine` into `sim/src/sim/town_engine.js` and run on the
server inside the world tick, on the shared clock and the company's ledger balance. The page sends
intent and draws what the server returns. It has no pause, no speed control and no save: the
invariants in the root `CLAUDE.md` apply to it in full. Rebuild the engine whenever `src/sim/`
changes, and commit the bundle with the change.

**The practice game**, `npm run build`, live at https://sim.lunarark.com. Single player, in the
browser, with its own fast clock, pause and local save. It touches nothing of value. It is where
rules are tried at speed before the live town gets them. See `docs/DEPLOY.md`.

`npm test` plays three lunar days against the rules directly. With `TOWN_URL` and `TOWN_KEY` set
the same player plays through a running server instead.

## Look

The interface uses the lunarark.com visual system, taken from the site's own stylesheet
(`lunarark_files/` at the repository root): Orbitron for titles and readings, Rajdhani for prose,
Space Mono for micro-labels, glass panels with hairline borders on a near-black violet ground,
violet leading and cyan supporting, and the cyan to violet gradient on anything meant to be
pressed. Gold is kept for sunlight only: the Day label and the base's mark on the Moon clock.
The tokens are the `:root` block at the top of `src/index.html`. Building colours on the map are
still placeholders and are not yet tied to the Codex cluster colours.

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
