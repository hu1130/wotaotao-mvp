import type { FastifyRequest } from "fastify";
import {
  ROLES,
  type ActorContext,
  type Role,
} from "@wotao/contracts";
import { AppError } from "./app-error.js";

export type Actor = ActorContext;

function readHeader(request: FastifyRequest, name: string): string | undefined {
  const value = request.headers[name];
  return Array.isArray(value) ? value[0] : value;
}

export function getActor(request: FastifyRequest): Actor {
  const role = readHeader(request, "x-role");
  const userId = readHeader(request, "x-user-id")?.trim();
  const encodedUserName = readHeader(request, "x-user-name")?.trim();
  const merchantId = readHeader(request, "x-merchant-id")?.trim() || null;
  let userName = encodedUserName;

  if (encodedUserName) {
    try {
      userName = decodeURIComponent(encodedUserName);
    } catch {
      userName = encodedUserName;
    }
  }

  if (!role || !ROLES.includes(role as Role) || !userId) {
    throw new AppError(
      401,
      "UNAUTHENTICATED",
      "请求缺少有效的角色或用户身份。",
    );
  }

  return {
    role: role as Role,
    userId,
    userName: userName || userId,
    merchantId,
  };
}

export function requireOperator(request: FastifyRequest): Actor {
  const actor = getActor(request);
  if (actor.role !== "OPERATOR") {
    throw new AppError(403, "FORBIDDEN", "只有运营人员可以执行内容审核操作。");
  }
  return actor;
}
