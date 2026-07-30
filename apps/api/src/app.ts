import Fastify, { type FastifyInstance } from "fastify";
import cors from "@fastify/cors";
import { PrismaClient } from "@prisma/client";
import { AppError } from "./domain/app-error.js";
import { registerReviewRoutes } from "./modules/review/review-routes.js";

export interface CreateAppOptions {
  prisma?: PrismaClient;
  logger?: boolean;
}

export async function createApp(
  options: CreateAppOptions = {},
): Promise<{ app: FastifyInstance; prisma: PrismaClient }> {
  const prisma = options.prisma ?? new PrismaClient();
  const app = Fastify({ logger: options.logger ?? false });

  await app.register(cors, {
    origin: process.env.WEB_ORIGIN
      ? [process.env.WEB_ORIGIN]
      : ["http://localhost:5174", "http://127.0.0.1:5174"],
    allowedHeaders: [
      "content-type",
      "x-role",
      "x-user-id",
      "x-user-name",
      "x-merchant-id",
      "x-request-id",
    ],
  });

  app.get("/health", async (request) => ({
    data: { status: "ok" },
    requestId: request.id,
  }));

  await registerReviewRoutes(app, prisma);

  app.setErrorHandler((error, request, reply) => {
    if (error instanceof AppError) {
      return reply.status(error.statusCode).send({
        errorCode: error.errorCode,
        message: error.message,
        requestId: request.id,
        ...(error.details ? { details: error.details } : {}),
      });
    }

    request.log.error({ err: error }, "Unhandled request error");
    return reply.status(500).send({
      errorCode: "INTERNAL_ERROR",
      message: "服务暂时无法完成请求。",
      requestId: request.id,
    });
  });

  app.addHook("onClose", async () => {
    await prisma.$disconnect();
  });

  return { app, prisma };
}
