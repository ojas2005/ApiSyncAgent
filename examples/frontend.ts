import type { UserResponse } from "./api-contracts";

export async function loadUser(id: number): Promise<UserResponse> {
  const response = await fetch(`/users/${id}`);
  return response.json();
}

export function displayName(user: UserResponse): string {
  return user.full_name;
}
