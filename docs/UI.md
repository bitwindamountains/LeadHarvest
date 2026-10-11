# LeadHarvest web UI: design contract

The Streamlit app (`app/`) is a tool for one operator or a small team, not a marketing page. People use it to start searches, watch them run, and take the results away. These rules keep it consistent; change them here first.

## Look

- **One theme, "night harvest":** colours and fonts come from `.streamlit/config.toml`. Finer styling comes from `app/assets/theme.css`, injected on every page:
  - Canvas: a dark paddy field (`#0b1410`) with a faint grid of gold grain dots and two soft glows.
  - Sidebar: darker soil (`#070e0a`).
  - Accent: palay gold (`#e0b04a`) is the only accent. Gold buttons and chips carry dark text (`#1a1305`).
  - Semantic colours: green, red, orange and blue are tuned for the dark canvas and used only for status.
  - It matches the LeadHarvest landing page, so the brand reads as one product.
- **Type:** Outfit for headings, Geist for text, Geist Mono for code and data.
- **Heading scale:**
  - One H1 per page: the page or run name.
  - H2 for sections ("What and where", "Leads").
  - No skipped levels.
- **Icons:** Material icons (`:material/...:`) only, never emojis. State is never shown by colour alone: every status icon has a text label next to it.
- **Cards:** glass surfaces with a faint gold top edge, used only where they group something. That means the search form, the "What happens next" guide (`key="lh-card-..."`), the sign-in card and the number cards. Everything else sits on the canvas.
- **Motion:** elements rise in once (420 ms, ease-out, staggered on the number cards). Cards lift and buttons press on hover and click. All of it is off under `prefers-reduced-motion`. There's no JavaScript animation: Streamlit strips scripts from `st.html`.

## Screens

| Screen | Its job | Primary action | States it must show |
|---|---|---|---|
| Sign-in | Keep strangers out | Sign in | Password not configured (setup error), wrong password (inline, after a 1 s delay), success |
| Search page | Start a run | Find leads | Setup problems (form hidden), validation errors (inline under the form), first visit (hint that runs appear in the sidebar), running (live progress per step) |
| Run page | Understand and take the results | Download / open the export | Completed, paused (with Resume), running elsewhere (with Take over), failed (with the log path), no businesses found (with what to try), segment selected (count and download) |
| Sidebar | Move between runs | New search | No runs yet, run history with status labels |

## Responsive rules

- **Widths to check:** 320, 768, 1024 and 1440 px.
- **Field pairs:** the form uses one `st.columns(2)` row per pair, so phones stack fields in reading order.
- **Numbers:** the run page's figures sit in a wrapping horizontal container, never `st.columns`, which would stack them one per line.
- **Sign-in on phones:** the brand panel hides itself below 760 px, leaving only the sign-in card.
- **Sidebar on phones:** Streamlit may open it over the page. That's its default and the app can't control it.

## Rejected patterns

- Emojis, purple or blue gradients, shadows on everything, and a card around every block.
- Centred marketing-style heroes inside the tool.
- Status shown only as a colour.

## Code layout

- **`app/streamlit_app.py`:** page setup and routing only.
- **`app/views/`:** one module per screen, plus `common.py` for running a pipeline with live progress.
- **`leadharvest.ui_support`:** all logic that can be tested without Streamlit.
- **`app/assets/`:** the logo, the mark, and the sign-in brand panel. `st.html` strips `<svg>` and `data:` images, so the panel is pure CSS.
