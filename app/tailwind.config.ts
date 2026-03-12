import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: "#4285F4",
        success: "#0F9D58",
        warning: "#F4B400",
        danger: "#DB4437",
      },
    },
  },
  plugins: [],
} satisfies Config;
