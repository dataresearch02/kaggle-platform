# Interface design

Shared styles live in `apps/web/src/styles.css`. Use the variables in `:root` for new screens rather than adding another font family, text size, or animation duration.

- **Typography:** local system UI fonts for navigation, headings, forms, and prose. This avoids external font downloads and late font swaps. Code uses the system monospace stack; mathematical notation keeps KaTeX fonts.
- **Type scale:** 12px metadata, 13px compact labels, 14px body and controls, 16px larger text, 18–20px titles, and 24–32px section and page headings. Tokens use rem units against the existing 14px root. Mobile form fields use 16px to avoid focus zoom.
- **Surfaces:** shared border and muted-text colors, 8px control corners, 12px cards, and 16px standard dialogs. Drawers, navigation rows, and notebook cells retain their purpose-specific geometry.
- **Motion:** 140ms for hover and menu feedback; 220ms for resizing navigation and sliding account drawers. Animate named properties rather than `all`. Account drawers support closing transitions in browsers with discrete-transition support.
- **Accessibility:** visible keyboard focus, dimmed modal backdrops without blur, and reduced-motion support for CSS effects and notebook table-of-contents scrolling. Use `preferredScrollBehavior()` from `motion.ts` for animated programmatic scrolling.

Validate changes with the web production build and Playwright suite. `e2e/design.spec.ts` checks responsive content width, shared typography, reduced motion, and keyboard focus. Live notebook navigation is covered by `integration/sidebar.spec.ts`.
