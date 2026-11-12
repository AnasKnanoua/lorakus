import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "src/api/schema.d.ts"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.strictTypeChecked],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Regle du projet (DEVELOPMENT.md §6) : l'API ne s'appelle que par le client genere.
      "no-restricted-globals": [
        "error",
        { name: "fetch", message: "Passer par le client genere (src/api/client.ts)." },
      ],
      "no-restricted-properties": [
        "error",
        { object: "globalThis", property: "fetch", message: "Passer par src/api/client.ts." },
        { object: "window", property: "fetch", message: "Passer par src/api/client.ts." },
      ],
      "@typescript-eslint/restrict-template-expressions": ["error", { allowNumber: true }],
    },
  },
  {
    // Configuration de Vite : executee par Node, typee par tsconfig.node.json.
    files: ["vite.config.ts"],
    languageOptions: {
      globals: globals.node,
      parserOptions: { projectService: false, project: "./tsconfig.node.json" },
    },
  },
  {
    // Le client genere est le seul endroit qui touche a fetch.
    files: ["src/api/client.ts", "src/test/**", "src/**/*.test.{ts,tsx}"],
    rules: { "no-restricted-globals": "off", "no-restricted-properties": "off" },
  },
  {
    files: ["public/sw.js"],
    ...js.configs.recommended,
    languageOptions: { sourceType: "script", globals: globals.serviceworker },
  },
);
