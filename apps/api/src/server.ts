import "dotenv/config";
import { createApp } from "./app.js";

process.env.DATABASE_URL ??= "file:./dev.db";

const port = Number(process.env.PORT ?? 3001);
const { app } = await createApp({ logger: true });

try {
  await app.listen({ host: "127.0.0.1", port });
} catch (error) {
  app.log.error(error);
  process.exit(1);
}
