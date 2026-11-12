import { ApiError, api, errorCode, type Schemas } from "./client";

export type Me = Schemas["MeResponse"];

export type LoginResult =
  | "ok"
  | "second_factor_required"
  | "second_factor_setup_required"
  | "invalid"
  | "too_many_attempts";

/** Utilisateur connecte, ou null s'il n'y a pas de session valide. */
export async function fetchMe(): Promise<Me | null> {
  const { data, response, error } = await api.GET("/api/v1/auth/me");
  if (response.status === 401) {
    return null;
  }
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

export async function login(
  email: string,
  password: string,
  secondFactor?: string,
): Promise<LoginResult> {
  const body = secondFactor ? { email, password, second_factor: secondFactor } : { email, password };
  const { response, error } = await api.POST("/api/v1/auth/login", { body });
  if (response.ok) {
    return "ok";
  }
  if (response.status === 429) {
    return "too_many_attempts";
  }
  if (response.status === 401) {
    return errorCode(error) === "second_factor_required" ? "second_factor_required" : "invalid";
  }
  if (response.status === 403 && errorCode(error) === "second_factor_setup_required") {
    return "second_factor_setup_required";
  }
  throw new ApiError(response.status, error);
}

export async function logout(): Promise<void> {
  await api.POST("/api/v1/auth/logout");
}
