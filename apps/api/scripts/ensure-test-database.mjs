import { mkdir, open } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl?.startsWith("file:./")) {
  throw new Error("The test database bootstrap only accepts a relative SQLite file URL.");
}

// Prisma 6 on Windows cannot reset a SQLite database that has never existed.
// Create only the empty file; `prisma migrate reset` remains the sole schema writer.
const databasePath = resolve("prisma", databaseUrl.slice("file:./".length));
await mkdir(dirname(databasePath), { recursive: true });
const handle = await open(databasePath, "a");
await handle.close();
