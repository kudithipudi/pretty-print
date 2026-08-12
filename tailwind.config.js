/** Tailwind config for pretty-print.
 *  Built with the lab standalone CLI (see README "Rebuilding Tailwind CSS").
 *  Design tokens per plans/00-STANDARDS.md §5: indigo-600 primary,
 *  slate-50/900 base, default sans stack for the app chrome. The printable
 *  article body is purposefully a serif stack (Georgia) since it is a paper
 *  artifact, per §5's allowance for purposefully-styled output.
 */
module.exports = {
  content: ["./app/templates/**/*.html"],
  theme: {
    extend: {},
  },
  plugins: [],
};