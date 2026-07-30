import "dotenv/config";
import { PrismaClient } from "@prisma/client";
import { seedDatabase } from "./seed-data.js";

process.env.DATABASE_URL ??= "file:./dev.db";

const prisma = new PrismaClient();

try {
  await seedDatabase(prisma);
  console.log("Seeded review MVP data.");
} finally {
  await prisma.$disconnect();
}
