# GMGN-Style Political Map Product Roadmap

## Product Thesis

Build a political prediction-market intelligence terminal where the map is the scanner. Users should see where unusual money is moving, select a colored region, understand the signal, and open the relevant trading pair without browsing a wall of election cards.

The product borrows GMGN's useful mental model: rank markets by abnormal activity and make the reason for each alert inspectable. It does not copy token-trading mechanics or present unverified wallet behavior as fact.

## Product Principles

- The map is the primary navigation surface.
- A region is colored only when it has a configured, active trading pair.
- Color communicates signal severity; selection uses an outline and never destroys the color meaning.
- Every alert explains what changed, how unusual it is, and which market is affected.
- Static fixtures, delayed data, and live detections are visibly distinguished.
- One primary pair represents each region on the map. Secondary pairs belong in the selected-region rail.

## Core User Loop

1. Open the global political activity map.
2. Scan regions ranked by abnormal-activity color.
3. Select a region.
4. Inspect the pair, probability, liquidity, signal score, and supporting evidence.
5. Add the region or market to a watchlist, or continue to the execution venue.
6. Receive an alert when the signal changes materially.

## Signal Model

The initial activity score is a 0-100 composite:

```text
activity score =
  30% volume anomaly
  25% order-flow imbalance
  20% probability velocity
  15% wallet concentration
  10% poll or related-market divergence
```

Severity thresholds:

| Score | Severity | Map treatment |
| --- | --- | --- |
| 0-49 | Normal | Blue |
| 50-69 | Elevated | Amber |
| 70-84 | High | Coral |
| 85-100 | Critical | Red |

The score must include component values, baseline window, observation time, source mode, and confidence before it is promoted from fixture to live.

## Information Architecture

### Global Map

- Country selector and political category filters
- Region fills driven by activity score
- Signal legend and source freshness
- Click selection with stable zoom behavior
- Ranked abnormal-activity feed

### Selected Region Rail

- Primary trading pair and current probability
- 1-hour, 24-hour, and 7-day changes
- Volume, liquidity, spread, and resolution date
- Active signal score and explanation
- Large trades and wallet concentration
- Related markets, polls, and political catalysts

### Market Detail

- Probability and volume history
- Order book and trade tape
- Signal timeline with component attribution
- Cross-market and polling divergence
- Resolution rules and venue links

## Delivery Plan

### Phase 1: Signal-Driven Map Foundation

Status: complete

- Replace hard-coded region tones with typed signal snapshots.
- Add severity scoring, a stable palette, and map legend.
- Preserve severity color while a region is selected.
- Show signal type, score, explanation, and fixture/live provenance in the rail.
- Add unit tests for score thresholds.

Acceptance criteria:

- Every configured region renders from the same signal contract.
- Selection does not change the meaning of the region color.
- Fixture signals are never labeled live.
- Typecheck, UI tests, and production build pass.

### Phase 2: Backend Signal API

Status: complete

- Add FastAPI region-market registry and signal response schemas.
- Calculate volume anomaly, price velocity, order-flow imbalance, and liquidity stress.
- Return score components, confidence, baseline window, and timestamps.
- Cache rolling baselines and expose freshness/degradation states.
- Replace frontend fixtures progressively, retaining a clear fallback mode.

Acceptance criteria:

- The map can load all region signals in one request.
- Signal scores are reproducible from returned components.
- Partial upstream failures do not blank the map.
- Stale data is visibly marked.

### Phase 3: Abnormal Activity Feed

Status: complete

- Rank signals by severity, freshness, liquidity, and confidence.
- Add filters for country, signal type, threshold, and time window.
- Synchronize feed selection with map selection and URL state.
- Add watchlists and browser notification preferences.

Acceptance criteria:

- A user can reach any critical signal in one click.
- Map, feed, and selected rail always show the same region and pair.
- Filters are shareable through the URL.

### Phase 4: Whale and Smart-Money Intelligence

Status: complete

- Normalize public trade and wallet activity where venue data permits.
- Detect large trades relative to market depth and historical trade size.
- Track wallet concentration and coordinated directional flow.
- Introduce wallet reputation only after sufficient resolved-market history.
- Explain uncertainty and avoid identity claims.

Acceptance criteria:

- Whale labels are based on transparent relative thresholds.
- Wallet scores show sample size and resolved-market history.
- No alert implies insider activity without verifiable evidence.
- Reputation requires five distinct resolved markets and combines 70% directional hit rate with 30% bounded realized return.

### Phase 5: Multi-Country Political Maps

Status: complete

- Generalize map configuration to country-specific GeoJSON or TopoJSON.
- Add country, region, feature-ID, projection, and market-registry adapters.
- Launch countries only when reliable market coverage exists.
- Start with the UK or Canada, then add countries based on venue liquidity.
- Keep official boundary provenance visible in the map legend.

Acceptance criteria:

- Adding a country does not require changes to shared signal UI.
- Unsupported regions remain neutral and non-interactive.
- Country switching clears invalid selection and preserves filters.

### Phase 6: Divergence and Catalyst Intelligence

Status: complete

- Compare prediction markets with polling, related contracts, and election models.
- Detect logically inconsistent probabilities across related markets.
- Correlate repricing windows with political news and scheduled events.
- Add human-readable catalyst summaries with source links.

Acceptance criteria:

- Divergence alerts name both compared sources and their timestamps.
- Related-market calculations account for fees and liquidity.
- Automated catalyst summaries remain traceable to source events.
- Related-outcome checks expose both observation timestamps, fee assumptions, and liquidity gating.

### Phase 7: Product Design and Decision Workflow

Status: complete

- Open directly into the map, scanner, and selected-market context instead of a marketing hero.
- Make live, delayed, fallback, and fixture provenance visible before users inspect a signal.
- Label the highest-priority anomalies directly on the map with score and pair context.
- Keep the country overview stable while region selection updates the outline and detail rail.
- Preserve a clear detect, select, validate, and act workflow across desktop and mobile.
- Add watchlist and venue actions to the selected-market rail.
- Move deep evidence into focused views so mobile does not render every chart at once.
- Replace unlabeled diagnostics with an inspectable source-status summary.

Acceptance criteria:

- The first desktop viewport contains at least one actionable signal and the map.
- Mobile reaches the ranked anomaly scanner before the geographic visualization.
- Every selected market shows its source mode and update time.
- Pair-specific metrics are never rendered for a fallback market that does not match the selected region.
- The map communicates its highest-priority anomalies without requiring legend cross-reference.
- Selecting a region does not remove neighboring signals from geographic context.
- Users can watch a region or open its matching venue market from the selected rail.
- Only one deep evidence view is expanded at a time.

### Phase 8: Interface Hierarchy and Visual Rhythm

Status: complete

- Consolidate brand, page title, context, navigation, and theme controls into one application header.
- Remove decorative full-width rules between page sections and use spacing to communicate hierarchy.
- Keep functional separators for tab state, scanner rows, and dense metric tables.
- Deduplicate selected-market metadata and expose the update time once.
- Preserve mobile access to the alternate primary route without crowding the header.
- Enforce one page-level heading per route.

Acceptance criteria:

- Home and Research use the same single-header structure.
- The map view has no stacked context bar, card header, and module label.
- Desktop and mobile layouts have no horizontal overflow.
- Navigation remains available at mobile widths.
- Heading levels describe the content hierarchy without duplicate `h1` elements.

### Phase 9: Production Status Communication

Status: complete

- Keep healthy data operation quiet and show update time without implementation details.
- Replace source modes and backend diagnostics with impact-based information, warning, and error notices.
- Remove mock, fixture, fallback, framework, and pipeline terminology from customer-facing copy.
- Express delayed data as the latest available information with a clear recency warning.
- Show unavailable regional coverage without exposing mismatched market internals.
- Preserve source diagnostics in application state for development and observability only.

Acceptance criteria:

- No rendered route exposes source mode, backend health, framework names, or fixture labels.
- Informational notices are neutral; delayed data is a warning; unavailable data is an error.
- Notices explain user impact and expected recovery behavior.
- Signal and market timestamps remain visible in plain language.

### Phase 10: Global Map Navigation

Status: complete

- [x] Preserve selected UK market identity when upstream market data is unavailable.
- [x] Provide coherent UK market history and order-book values for all configured regions.
- [x] Replace the country dropdown with a map-based country selection mode.
- [x] Let users move from a world overview into a country map without losing signal filters.
- [x] Preserve country and region selection in the shareable URL.

### Phase 11: Selected-Market Trading Summary

Status: complete

- [x] Calculate 1-hour, 24-hour, and 7-day probability movement from timestamped history.
- [x] Add current probability and movement windows to the selected-region rail.
- [x] Add 24-hour volume and available liquidity in compact market units.
- [x] Withhold movement windows when no suitably timed observation exists.
- [x] Validate the summary across live and latest-available UK market data.

### Phase 12: Contract Resolution Context

Status: complete

- [x] Normalize venue, close time, contract description, and resolution source metadata.
- [x] Show verified venue and close time without fabricating unavailable fallback values.
- [x] Keep detailed resolution guidance collapsed until requested.
- [x] Reject malformed dates and unsafe resolution-source links.
- [x] Validate contract context across live and latest-available market states.

### Phase 13: Market Lifecycle Clarity

Status: complete

- [x] Normalize open, closed, inactive, and unknown lifecycle states from venue flags.
- [x] Mark closed markets beside the primary title and selected-region title.
- [x] Label closed-market probability and volume as historical statistics.
- [x] Replace execution-oriented copy for closed contracts with historical viewing language.
- [x] Keep a verified open political contract as the default market.

### Phase 14: Unified Global Signal Map

Status: complete

- [x] Render a persistent Natural Earth world layer and country-region signal layers in one map canvas.
- [x] Support pointer drag and zoom without switching to separate country map containers.
- [x] Select supported countries or configured regions directly from the world view.
- [x] Default the signal scanner to all countries while preserving selected-country live overrides.
- [x] Add a manual country scope and persist it with map, region, and signal filters in the URL.
- [x] Preserve scanner-first mobile ordering and prevent horizontal map overflow.

### Phase 15: Interruptible Live Map Tour

Status: complete

- [x] Start the default home route on the live world map with global signal scope.
- [x] Rotate through verified-open regions ranked by abnormal activity.
- [x] Move the existing map camera and selected market without mounting a second map.
- [x] Stop rotation after country selection, region selection, pointer drag, or map click.
- [x] Keep explicit shared URLs paused and provide a compact play/pause control.
- [x] Exclude closed and unknown-lifecycle contracts from automatic rotation.

### Phase 16: Europe Political Markets

Status: complete

- [x] Add Europe as a continental map adapter using Natural Earth country boundaries.
- [x] Add open political markets for France, Germany, Spain, Italy, and Iceland.
- [x] Reuse global scanner, watchlist, lifecycle, venue, and URL-selection behavior.
- [x] Add verified-open fallback identity, probability, liquidity, and close-time context.
- [x] Validate Europe focus and global-to-Europe navigation on desktop and mobile.

### Phase 17: Country-Accurate World and Detail Layers

Status: complete

- [x] Replace the synthetic Europe adapter with independent country adapters.
- [x] Show one activity surface and label per configured country at world scale.
- [x] Render only the focused country's subdivisions after selection or auto-tour.
- [x] Add regional boundaries for France and Länder boundaries for Germany.
- [x] Keep national contracts national while preserving internal boundary context.
- [x] Anchor Germany's Berlin market to the Berlin state polygon.

### Phase 18: Global Live Trade Tape

Status: complete

- [x] Proxy the latest public trades without restricting the feed to one contract.
- [x] Normalize market identity, outcome, side, price, size, and timestamp.
- [x] Poll independently from the selected map market without synthetic fallback.
- [x] Rotate recent prints in a compact lower-left map overlay.
- [x] Link each print to its Polymarket event and respect reduced-motion settings.

### Phase 19: Animated Auto-Tour Camera

Status: complete

- [x] Replace automatic camera jumps with staged zoom-out, pan, and zoom-in motion.
- [x] Focus automatic navigation on the selected region rather than only its country.
- [x] Cancel in-flight motion immediately after pointer or manual selection input.
- [x] Debounce the next tour interval until camera motion has settled.
- [x] Keep manual country navigation immediate and deterministic.

### Phase 20: Fullscreen Map Control

Status: complete

- [x] Replace the country-view world button with a compact fullscreen control.
- [x] Group fullscreen and auto-tour controls inside the map.
- [x] Preserve auto-tour state when entering or exiting fullscreen.
- [x] Fill the fullscreen viewport while keeping the ocean matched to the surface.

### Phase 21: Complete Signal Ranking Pagination

Status: complete

- [x] Remove the hidden five-result cap from the global signal ranking.
- [x] Include scores below 50 whenever the Score filter is set to All.
- [x] Add stable rank numbers across paginated results.
- [x] Add result ranges, page jumps, and previous/next controls.
- [x] Reset or clamp pages when filters and result counts change.

### Phase 22: Regional Trade and Country Navigation

Status: complete

- [x] Restrict the live map tape to configured regional political market pairs.
- [x] Remove the opaque trade-tape surface so the map remains visible beneath it.
- [x] Keep non-focused configured countries colored and selectable during country detail mode.
- [x] Render the focused country's subdivisions while other countries remain single polygons.

### Phase 23: Kalshi Political Pairs

Status: complete

- [x] Register verified-open Kalshi election events for the eight Polymarket-comparable US regions.
- [x] Proxy Kalshi's public Events API through a validated server route.
- [x] Normalize leading outcome, probability, 24-hour volume, lifecycle, and source metadata.
- [x] Display Polymarket and Kalshi as distinct trading pairs in the selected-region rail.
- [x] Keep Kalshi data unavailable rather than substituting synthetic prices.

### Phase 24: Kalshi-Only US Political Coverage

Status: complete

- [x] Allow a map region to exist without a Polymarket market slug.
- [x] Add 20 open Kalshi-only state election markets selected by liquidity and regional relevance.
- [x] Keep Kalshi-only regions out of the abnormal auto-tour until venue signal scoring exists.
- [x] Show truthful zero-score signal context instead of fabricating whale or anomaly activity.
- [x] Preserve scanner pagination, map selection, watchlists, and mobile trading-pair layout.

### Phase 25: Venue Volume Discovery

Status: complete

- [x] Load all configured Kalshi events in API-safe batches instead of only the selected region.
- [x] Add a URL-persisted Kalshi volume filter with a default $1,000 floor and an explicit Off state.
- [x] Include Kalshi-only markets in ranking when they meet the selected volume floor.
- [x] Color and label volume-qualified regions distinctly from abnormal signal regions.
- [x] Keep signal-qualified results first, then sort volume-only results by 24-hour volume.
- [x] Preserve ranking pagination as the eligible market set expands.
- [x] Keep map polygons independent from scanner score thresholds.
- [x] Encode polygon scores continuously from blue to red and liquidity through opacity.

### Phase 26: Conflict and Ceasefire Markets

Status: complete

- [x] Verify open Polymarket contracts against the live Gamma API before registration.
- [x] Add selectable national markets for Ukraine, Russia, Israel, Iran, Lebanon, and Palestine.
- [x] Cover peace agreements, ceasefires, withdrawal, and ceasefire-phase contracts.
- [x] Keep unconnected conflict analytics at score zero instead of fabricating anomaly signals.
- [x] Preserve exact event links, open lifecycle metadata, and deterministic fallback identities.
- [x] Show the selected venue outcome and current probability beside the market title.

### Phase 27: Ukraine Locality Markets

Status: complete

- [x] Add a simplified Ukraine oblast boundary layer with explicit source provenance.
- [x] Keep the national peace market as fallback coverage for oblasts without a locality contract.
- [x] Add verified-open Huliaipole, Kostyantynivka, Myrne, Stinky, and Bilytske contracts.
- [x] Map locality contracts to exact coordinates and their Donetsk or Zaporizhzhia oblast.
- [x] Use separate selectable town markers where multiple contracts share one oblast.
- [x] Keep locality anomaly scores at zero until conflict-specific analytics are connected.

### Phase 28: Kalshi Market Analytics

Status: complete

- [x] Load public Kalshi order books, recent trades, and hourly price candles.
- [x] Normalize Kalshi depth, spread, imbalance, flow, volatility, and movement into the shared analytics model.
- [x] Detect unusually large public prints using median-size and executable-depth thresholds.
- [x] Render Kalshi depth, market snapshot, flow evidence, history, and replay in the existing market rail.
- [x] Cache short-lived analytics responses and tolerate partial upstream failures.
- [x] Keep wallet concentration and trader reputation unavailable because public Kalshi trades do not expose wallet identities.

### Phase 29: European Market Discovery and Shared Venue Cache

Status: complete

- [x] Expand European election coverage to Romania, Hungary, Sweden, Greece, Serbia, and Bulgaria.
- [x] Show multiple verified-open Polymarket election and government pairs per supported country.
- [x] Batch configured event discovery through one cursor-compatible Gamma request.
- [x] Cache event discovery and history for five minutes with stale serving during upstream failures.
- [x] Cache high-fanout order-book and trade reads for short windows at the server and CDN layers.
- [x] Share Kalshi event and analytics responses instead of forwarding every browser poll upstream.
- [x] Keep WebSocket and short-lived depth data responsive while preventing per-client REST amplification.

### Phase 30: Railway Venue Aggregation

Status: complete

- [x] Add Railway-native batched Polymarket event discovery.
- [x] Add Railway-native Kalshi event, order-book, trade, and candle aggregation.
- [x] Route frontend venue reads through Railway before the Vercel fallback.
- [x] Coalesce concurrent cache misses into one upstream request per venue key.
- [x] Preserve short cache windows for live data and longer windows for history.
- [x] Verify that twenty concurrent readers produce one upstream request.

### Phase 31: Tiered Venue Monitoring

Status: complete

- [x] Rank each venue catalog into hot, warm, and discovery-only tiers.
- [x] Stagger summary refreshes with bounded per-tick concurrency.
- [x] Apply shared per-venue token buckets to every upstream REST cache miss.
- [x] Add venue cooldowns after HTTP 429 responses.
- [x] Reserve Polymarket WebSocket capacity for both hot and user-selected markets.
- [x] Expose tier assignments, refresh state, errors, and rate-budget telemetry.

### Phase 32: Shared Cache and Product Persistence

Status: planned

- [ ] Add Redis for shared venue responses, catalog snapshots, score baselines, and scheduler state.
- [ ] Use a Redis lease so exactly one Railway replica owns catalog scans and monitoring jobs.
- [ ] Publish refreshed snapshots through Redis so API replicas remain stateless and consistent.
- [ ] Preserve stale venue data across Railway restarts and transient upstream failures.
- [ ] Add PostgreSQL for users, watchlists, alert rules, notification history, and saved market views.
- [ ] Persist historical regional scores and market snapshots for charting and anomaly backtesting.
- [ ] Define retention, migration, backup, and restore policies before storing production user data.
- [ ] Keep Redis optional for single-replica local development and provide deterministic in-memory fallbacks.

### Phase 33: Volume Terrain Map Concept

Status: complete

- [x] Replace blocky marker pyramids in the product direction with sparse thin volume pillars.
- [x] Model regional volume as a natural mountain field using a center-weighted height distribution, superseded by the Gaussian mixture in Phase 37.
- [x] Remove background surfaces from live trade map text so trade prints read as direct map annotations.
- [x] Add an interim tilted SVG map treatment so country views start moving toward the curved globe concept.
- [x] Port the terrain model into an R3F/Three.js globe with real repository boundaries.
- [x] Bind the 3D globe to country selection, regional selection, live volume, and trade annotations.
- [x] Tune camera framing, lighting, and mobile density from visual QA against the approved concept.

### Phase 34: Globe Concept Fidelity

Status: complete

- [x] Add nearby configured market terrain around the selected country.
- [x] Vary pillar color and width by mountain height while preserving sparse coverage.
- [x] Increase selected-region prominence without clipping desktop or mobile framing.
- [x] Add stronger land, ocean, and extrusion depth cues from visual QA.
- [x] Keep contextual trade annotations on desktop and prioritize the selected label on mobile.

### Phase 35: Atmospheric Horizon and Score Color Parity

Status: complete

- [x] Treat the concept's neutral neighboring countries as visual reference only; preserve flat-map score coloring as the product requirement.
- [x] Color every configured globe country from its highest open regional activity score.
- [x] Derive each volume mountain's pillar colors from the same score color as its country.
- [x] Add distance-aware atmospheric obscuring at the far sphere horizon.
- [x] Verify score-color and horizon behavior on compact Europe and continent-scale views.

### Phase 36: Surface Reflection, Shadows, and Raised Borders

Status: complete

- [x] Add a procedural reflective ripple texture to the ocean surface.
- [x] Enable soft cast and receive shadows for land polygons and volume pillars.
- [x] Render borders as separate paths slightly above their polygon surfaces.
- [x] Verify reflection, shadow projection, and border elevation on desktop and mobile.

### Phase 37: Focused Pillar Hierarchy and Top Lighting

Status: complete

- [x] Scale down pillar count, height, and width outside the focused country.
- [x] Replace the binomial-style field with a truncated Gaussian mixture that concentrates most pillars around the regional market center.
- [x] Preserve a sparse uniform tail so the volume mountain retains a natural footprint.
- [x] Fix the key light above the globe so projected shadows travel downward.
- [x] Concentrate ocean reflection lighting in the upper hemisphere.
- [x] Verify focused-country hierarchy, concentration, shadow direction, and upper-ocean reflection across Europe, US, and mobile views.

### Phase 38: Pillar-Root Surface Gradients

Status: complete

- [x] Replace flat polygon cap fills with geodesic gradient materials.
- [x] Anchor maximum score-color saturation beneath each region's pillar center.
- [x] Reduce saturation and slightly lift lightness toward polygon borders.
- [x] Preserve score hue families, elevated borders, and shadow reception.
- [x] Verify gradient continuity and score readability across Europe, US, and mobile views.

### Phase 39: Camera-Fixed Top Light and Realistic Shading

Status: complete

- [x] Keep the shadow-casting key light outside the rotating globe group.
- [x] Reposition the key from camera screen-up coordinates so it remains visually overhead through orbit interaction.
- [x] Track a stable map target so pillar shadows project downward in the view.
- [x] Use a tuned PCF shadow map with a tighter orthographic shadow frustum; VSM was rejected because it suppressed generated point-layer pillars.
- [x] Reduce ambient wash and add ACES filmic tone mapping for stronger material depth.
- [x] Verify shadow direction before and after globe interaction, plus reflection and score-color fidelity on desktop and mobile.

### Phase 40: Visible Pillar Shadow Projection

Status: complete

- [x] Register generated `three-globe` point meshes as shadow casters by object type.
- [x] Disable pillar height transitions before shadow registration.
- [x] Reduce normal bias below the thin pillar radius so shadows are not erased.
- [x] Tighten the shadow frustum and raise its map resolution to resolve narrow pillars.
- [x] Keep land and ocean materials as explicit shadow receivers while pillars remain caster-only.
- [x] Add analytic light-ray shadow projections for pillars that remain below native shadow-map pixel resolution.
- [x] Verify visible pillar shadows on land and coastal water at desktop and mobile scales.

### Phase 41: Physical Borders and Seamless Ocean Reflection

Status: complete

- [x] Replace elevated path lines with merged, deduplicated short-wall geometry.
- [x] Make country and regional wall faces cast and receive directional shadows.
- [x] Replace non-periodic ocean wave frequencies with a seamless periodic field.
- [x] Increase procedural normal and reflection environment resolution.
- [x] Retune the ocean as a rough dielectric surface instead of a metallic clearcoat.
- [x] Verify border depth and ocean continuity across Europe, US, and mobile views.

### Phase 42: Restore Land and Pillar Shadow Contrast

Status: complete

- [x] Reduce environment fill on land caps and physical border walls.
- [x] Restore darker land extrusion faces beneath elevated regions.
- [x] Increase projected pillar-shadow density and opacity.
- [x] Compare the revised scene against the Phase 40 shadow baseline.

### Phase 43: Volumetric Border Walls

Status: complete

- [x] Give country and regional borders physical tangent-plane width.
- [x] Build separate horizontal top and vertical side faces.
- [x] Keep top faces light and side faces shaded under the fixed overhead light.
- [x] Preserve wall shadow casting and reception.
- [x] Verify wall width, joints, and shading across Europe, US, and mobile views.

### Phase 44: Native-Only Shadow Comparison

Status: complete

- [x] Disable the analytic pillar-shadow core and penumbra layers.
- [x] Retain native directional-light PCF shadows for pillars, land, and walls.
- [x] Compare native-only rendering against the Phase 43 analytic-overlay view.
- [x] Verify France and US desktop views before selecting the preferred treatment.
- [x] Keep native-only rendering as the current state for one neutral shadow hue, accepting reduced visibility from the smallest European pillars.

### Phase 45: Refined Walls, Gradients, and Pillar Distribution

Status: complete

- [x] Make volumetric border walls thinner, shorter, and less reflective.
- [x] Increase the center-to-edge saturation contrast within scored regions.
- [x] Raise saturation for low-score yellow regions without changing global legend colors.
- [x] Replace broad uniform pillar heights with a steep mountain distribution.
- [x] Limit tall central spikes and bias most pillars toward shorter heights.
- [x] Verify France and US desktop/mobile composition and performance.

### Phase 46: Deterministic Single-Layer Pillar Shadows

Status: complete

- [x] Diagnose native shadow loss against shadow-map texel size and reduced pillar heights.
- [x] Keep native PCF shadows for land and volumetric walls.
- [x] Remove pillars from the native shadow map to prevent double rendering.
- [x] Replace the colored core and penumbra pair with one neutral projected layer.
- [x] Include shorter pillars in the deterministic projection fallback.
- [x] Verify repeatable shadows across France, US, reloads, and mobile.

### Phase 47: 3D-First Application Entry

Status: complete

- [x] Make the country R3F globe the default application map view.
- [x] Remove the initial 2D world-map flash before URL hydration.
- [x] Preserve the 2D global overview behind the explicit `?view=world` URL.
- [x] Update filter parsing and serialization for the new default.
- [x] Verify `/` opens the 3D globe and `?view=world` still opens the 2D map.

### Phase 48: Orbit Stability and Interaction Performance

Status: complete

- [x] Reduce orbit rotation and zoom sensitivity with controlled damping.
- [x] Force native shadow-map refreshes throughout drag interactions.
- [x] Clamp projected pillar rays inward so orbiting cannot make them miss the globe.
- [x] Cap focused, selected, and contextual pillar counts per region.
- [x] Merge non-interactive pillar geometry and reduce radial tessellation.
- [x] Reduce native land/wall shadow-map cost while preserving visible depth.
- [x] Verify shadows before and after repeated drags on desktop and mobile.
- [x] Confirm the requested port `3000` development server remains stopped.

### Phase 49: Transparent Globe Surround

Status: complete

- [x] Remove the flat color behind the spherical globe so the scene blends into the page.
- [x] Preserve the ocean material, atmospheric horizon, and transparent WebGL canvas.
- [x] Verify the result at desktop and mobile viewports and save screenshots.

### Phase 50: Northern Market Orbit Rail

Status: complete

- [x] Add a fixed horizontal orbit range around the selected country focus.
- [x] Keep the range broad enough to traverse the US, Europe, and Middle East.
- [x] Prevent downward rotation into southern and underside views.
- [x] Verify both horizontal endpoints and the northern tilt range.
- [x] Confirm constrained dragging remains fluent on desktop and mobile.

### Phase 51: Direct 3D Country Navigation

Status: complete

- [x] Make contextual mapped-country polygons selectable from the focused globe.
- [x] Keep focused regional polygons mapped to region selection.
- [x] Ignore drag-release events so orbit gestures do not trigger navigation.
- [x] Verify country-to-country and region-to-region switching by direct click.
- [x] Save desktop and mobile interaction screenshots.

### Phase 52: Stronger Contextual Pillars

Status: complete

- [x] Reduce the height and width suppression applied outside the focused country.
- [x] Increase contextual pillar density while preserving a strict per-region cap.
- [x] Compare focused and contextual hierarchy across the European market cluster.
- [x] Verify desktop/mobile composition and interaction performance.

### Phase 53: Simplified Regional Border Walls

Status: complete

- [x] Simplify province and state wall rings before volumetric extrusion.
- [x] Preserve full-resolution land fills, gradients, and geographic hit testing.
- [x] Measure a 51-85% wall-vertex reduction across France, Germany, the UK, Ukraine, and US states.
- [x] Verify walls remain aligned, closed, and visually smooth on desktop/mobile.
- [x] Confirm orbit and country-switch interaction remains responsive.

### Phase 54: Persistent Globe Context Layers

Status: complete

- [x] Keep the Canvas and WebGL context mounted across country selection.
- [x] Split static world polygons from focused regional polygons and walls.
- [x] Keep non-focused pillar geometry stable in per-country merged layers.
- [x] Rebuild only focused-country pillars and province-level geometry.
- [x] Verify the same Canvas survives direct country clicks with shadows intact.
- [x] Measure approximately 390-405 ms focus updates on desktop/mobile and save screenshots.

### Phase 55: Fullscreen Market Workspace

Status: complete

- [x] Replace the framed grey product shell with an edge-to-edge market workspace.
- [x] Add a compact icon navigation rail with accessible labels and theme control.
- [x] Consolidate market identity, live state, probability, save, and share actions into the top header.
- [x] Fill the first desktop viewport with the 3D globe and a fixed market overview inspector.
- [x] Preserve the activity scanner and evidence views below the primary globe workspace.
- [x] Reorder mobile content as globe, overview, activity, and evidence with a bottom navigation rail.
- [x] Verify nonblank WebGL output, exact viewport framing, and zero horizontal overflow.
- [x] Save desktop and mobile screenshots under `tmp/frontend-fullscreen-workspace/`.

### Phase 56: Persistent Pillar Contact Shadows

Status: complete

- [x] Replace the timed shadow-registration window with an idempotent persistent mesh registry.
- [x] Reapply caster and receiver flags when `r3f-globe` creates or replaces internal meshes.
- [x] Register merged pillar meshes as native shadow casters.
- [x] Replace analytical line segments with tapered surface-conforming ribbon geometry.
- [x] Add denser elliptical contact patches at pillar roots with independent opacity.
- [x] Control z-fighting with a small radial lift, polygon offset, and disabled depth writes.
- [x] Verify shadows after repeated orbit drags and direct country focus switching.
- [x] Save desktop and mobile screenshots under `tmp/frontend-persistent-shadow-ribbons/`.

### Phase 57: Selected Country Side Skirt

Status: complete

- [x] Share explicit altitude constants across land caps, regional caps, and boundary walls.
- [x] Detect national-market focus without changing state or province selection geometry.
- [x] Extend the lower active-country wall to overlap the selected regional cap.
- [x] Use one selected-extrusion side color for the land side and extended lower wall.
- [x] Preserve the short, lighted upper border wall above the selected cap.
- [x] Verify France national focus and California state-focus regression behavior.
- [x] Save desktop and mobile screenshots under `tmp/frontend-selected-border-skirt/`.

### Phase 58: Globe-Fixed Lighting

Status: complete

- [x] Define one globe-local source, target, and projection ray for all shadow paths.
- [x] Transform the native directional light from the globe group matrix.
- [x] Remove camera-up and camera-forward coupling from pillar contact shadows.
- [x] Rebuild projected ribbon geometry only when pillar data changes.
- [x] Keep native and projected shadow directions aligned through globe focus changes.
- [x] Verify fixed geographic shadow direction at both orbit-rail extremes.
- [x] Save desktop and mobile screenshots under `tmp/frontend-globe-fixed-light/`.

### Phase 59: Consistent Selected Wall Side Color

Status: complete

- [x] Replace the warm selected extrusion override with the shared cool wall-side color.
- [x] Apply one side color across selected country sides, the extended lower skirt, and ordinary country walls.
- [x] Preserve the selected cap gradient, lighted wall tops, extrusion height, and shadows.
- [x] Verify France at desktop and mobile viewports against neighboring wall sides.
- [x] Save desktop and mobile screenshots under `tmp/frontend-consistent-wall-side/`.

### Phase 60: Reduced Regional Wall Height

Status: complete

- [x] Reduce selected and ordinary regional boundary wall heights.
- [x] Preserve a subtle selected-region height distinction.
- [x] Keep national outer skirts, wall widths, cap elevations, colors, and lighting unchanged.
- [x] Verify France at desktop and mobile viewports.
- [x] Save screenshots under `tmp/frontend-reduced-regional-walls/`.

### Phase 61: Selected Skirt Wall Coverage

Status: complete

- [x] Widen the selected country skirt beyond the outer regional wall.
- [x] Extend the skirt to cover the outer regional wall sides.
- [x] Leave a small height clearance so the illuminated regional wall top remains visible.
- [x] Preserve internal regional wall dimensions and the selected side color.
- [x] Verify France at desktop and mobile viewports.
- [x] Save screenshots under `tmp/frontend-selected-skirt-coverage/`.

### Phase 62: Unified Border Precision

Status: complete

- [x] Detect the active country perimeter from unshared regional boundary edges.
- [x] Reuse the same high-precision perimeter for country and outer regional walls.
- [x] Apply lighter simplification to country walls and stronger simplification to shared regional walls.
- [x] Keep national coastlines precise without producing serrated short wall segments.
- [x] Verify France at desktop and mobile viewports.
- [x] Save screenshots under `tmp/frontend-unified-border-precision/`.

### Phase 63: Natural Wall-Side Shading

Status: complete

- [x] Lighten the selected country and region side base color.
- [x] Increase the globe-fixed key-light intensity.
- [x] Reduce ambient, hemisphere, secondary-light, and environment fill on walls.
- [x] Preserve fixed globe-relative lighting and native shadow projection.
- [x] Verify wall-face contrast at desktop and mobile viewports.
- [x] Save screenshots under `tmp/frontend-natural-wall-shading/`.

### Phase 64: Single Regional Border Layer

Status: complete

- [x] Identify the overlap between built-in polygon extrusion sides and custom boundary walls.
- [x] Hide routine regional polygon sides so custom boundary geometry owns internal borders.
- [x] Retain a naturally lit extrusion side only for a uniquely selected raised region.
- [x] Extend the precise active-country skirt to cover ordinary regional cap sides.
- [x] Use one shared standard-material side color across polygon skirts and boundary walls.
- [x] Verify national focus at desktop and mobile viewports.
- [x] Save screenshots under `tmp/frontend-single-region-border/`.

### Phase 65: Single Owner Per Shared Border

Status: complete

- [x] Identify duplicate custom walls generated independently by adjacent regions.
- [x] Assign every shared raw boundary edge to one owning polygon.
- [x] Prefer the selected polygon as owner when a selected region shares an edge.
- [x] Skip non-owner copies before regional path simplification and mesh generation.
- [x] Verify border intersections at desktop and mobile viewports.
- [x] Save screenshots under `tmp/frontend-single-owner-border/`.

### Phase 66: Deferred Intro Data Layers

Status: complete

- [x] Match the data-layer reveal delay to the globe's 1200ms intro rotation.
- [x] Keep the independent regional polygon globe hidden during the main globe rotation.
- [x] Keep country and regional border walls hidden during the intro rotation.
- [x] Keep focused and contextual pillars plus projected shadows hidden during rotation.
- [x] Defer live trade labels with the same reveal gate.
- [x] Preserve immediate layer updates after the one-time initial reveal.
- [x] Verify rotating and settled states at desktop and mobile viewports.
- [x] Save screenshots under `tmp/frontend-deferred-intro-layers/`.

### Phase 67: Per-Surface Pillar Shadow Registration

Status: complete

- [x] Record the correct shadow receiver altitude on each generated pillar.
- [x] Project selected-region shadows onto the elevated selected cap.
- [x] Project other focused-country shadows onto their regional caps.
- [x] Keep contextual ribbons on the ocean receiver shell so real land shadows remain depth-correct without a floating overlay.
- [x] Keep border walls as shadow casters but exclude their vertical sides from pillar-shadow reception.
- [x] Disable shadow-map reception in polygon side shaders while preserving directional material shading.
- [x] Verify London and Berlin shadow registration at desktop and mobile viewports.
- [x] Save screenshots under `tmp/frontend-context-shadow-registration/`.

### Phase 68: Persistent Context Pillars and Live Trade FIFO

Status: complete

- [x] Keep every non-focused country pillar field mounted and visible while switching US states.
- [x] Preserve European context pillar counts across California-to-Florida selection.
- [x] Remove synthetic volume fallback popups and only map actual Polymarket venue trades.
- [x] Append unseen trade IDs to a three-slot FIFO queue.
- [x] Expire each popup after seven seconds without replaying unchanged polling results.
- [x] Remove popup text outlines and use fixed dark gray text on desktop and mobile.
- [x] Add regression coverage for venue matching, FIFO capacity, and expiry.
- [x] Save screenshots under `tmp/frontend-persistent-context-live-trade-fifo/`.

## Deployment and Operations

- Frontend: Vercel preview and production deployments.
- Backend and scheduled signal workers: Railway.
- CI: typecheck, UI tests, backend tests, and Next.js production build.
- Observability: endpoint latency, upstream error rate, signal freshness, stream reconnects, and fixture fallback usage.

## Immediate Next Work

- [x] Complete Phase 1 and validate the map interaction.
- [x] Define the FastAPI `RegionSignal` and `SignalComponent` schemas.
- [x] Add a batch `/api/signals/regions` endpoint backed by current stream metrics.
- [x] Replace the selected live region's fixture signal when enough backend samples are available.
- [x] Add the first ranked abnormal-activity feed with threshold filtering and map selection.
- [x] Add signal-type and time-window filters with URL persistence.
- [x] Add persistent region watchlists, watched-only filtering, and opt-in browser notification preferences.
- [x] Detect large public trades using transparent median-size and executable-depth thresholds.
- [x] Remove synthetic wallet identities and placeholder whale-buy claims.
- [x] Normalize documented public proxy-wallet trades and add sample-gated concentration scoring.
- [x] Replace the Home hero with a product-first market intelligence shell.
- [x] Add explicit source provenance, in-map anomaly labels, and selected-market actions.
- [x] Reduce mobile depth with scanner-first ordering and tabbed evidence views.
- [x] Withhold pair-specific metrics and charts when regional market coverage does not match.
- [x] Keep the country map camera stable while selecting regional trading pairs.
- [x] Add the United Kingdom regional map, political-pair registry, signal fixtures, and ONS boundary provenance.
- [x] Cache unchanged replay baselines and expose stale signal degradation through the API and scanner.
- [x] Gate wallet reputation behind five resolved markets and expose the resolved-history sample.
- [x] Add fee-aware related-market consistency checks and source-linked political catalyst windows.
- [x] Add a timestamped polling-derived election-model baseline for market comparison.
- [x] Add a compact selected-market trading summary with time-aware movement windows.
- [x] Add verified venue, close-time, and contract-resolution context.
- [x] Distinguish closed contracts from open markets in titles, statistics, and actions.
- [x] Unify world and regional navigation in one pannable map with global signal scope.
- [x] Add an interruptible live tour across verified-open high-activity regions.
- [x] Launch the Europe country-market layer with five open political contracts.
- [x] Split European markets into country-accurate world and regional detail layers.
- [x] Add a rolling regional-pair live trade tape to the map.
- [x] Animate and debounce region-to-region auto-tour camera movement.
- [x] Add a fullscreen map control beside auto-tour.
- [x] Page the complete signal ranking without hiding normal-score regions.
- [x] Preserve country navigation while a focused country's subregions are visible.
- [x] Add live Kalshi political pairs for the configured US regions.
- [x] Add liquid Kalshi-only state political markets without requiring Polymarket equivalents.
- [x] Surface Kalshi-only markets on the map and ranking through an optional volume filter.
- [x] Add verified-open Middle East and Russia-Ukraine conflict markets to the world map.
- [x] Add Ukraine oblast context and selectable locality-level war markets.
- [x] Bring public Kalshi market analytics to parity with the Polymarket evidence views.
- [x] Expand and batch European Polymarket coverage behind shared venue caches.
- [x] Make Railway the primary shared data plane for both venues.
