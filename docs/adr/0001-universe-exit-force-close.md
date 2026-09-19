# Force-close Positions on Universe exit

When an Instrument leaves the tradeable Universe (e.g., dropped from Nifty 500 at a quarterly reconstitution), any open Position in it is force-closed at the next Rebalance rather than being grandfathered until a natural exit Signal fires.

**Why**: at retail size (₹50k–₹1L Live-Small, single-digit lakhs Live-Scale) the market impact of a forced close is negligible, whereas grandfathering introduces a "legacy Position" state with different Rebalance rules from the main flow — a second code path that must be tested, monitored, and kept in sync as the Meta-Learner evolves. Universe exit is also a real signal in itself: names dropped from Nifty 500 have typically lost liquidity or fundamental standing, and continuing to hold them post-exit contradicts the Universe rules we ostensibly enforce for a reason. If we later scale to a size where forced closure creates meaningful slippage (roughly ₹10 Cr+ AUM based on Nifty 500 mid-cap turnover), we revisit this via superseding ADR.

**Considered alternative**: grandfather positions until a natural exit Signal — rejected for the reasons above.
