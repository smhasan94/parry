import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useCommunityPacks(params?: { category?: string; search?: string }) {
  return useQuery({
    queryKey: ["community-packs", params?.category, params?.search],
    queryFn: () => api.listCommunityPacks(params),
  });
}

export function useCommunitySubscriptions() {
  return useQuery({
    queryKey: ["community-subscriptions"],
    queryFn: () => api.listCommunitySubscriptions(),
  });
}

export function useCommunityCategories() {
  return useQuery({
    queryKey: ["community-categories"],
    queryFn: () => api.listCommunityCategories(),
  });
}

export function useInstallPack() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (packId: string) => api.installCommunityPack(packId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["community-packs"] });
      qc.invalidateQueries({ queryKey: ["community-subscriptions"] });
    },
  });
}

export function useUninstallPack() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (packId: string) => api.uninstallCommunityPack(packId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["community-packs"] });
      qc.invalidateQueries({ queryKey: ["community-subscriptions"] });
    },
  });
}

export function usePublishPack() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      name: string;
      description?: string;
      category: string;
      rules: Array<{ name: string; pattern: string; target?: string; severity?: string }>;
    }) => api.publishCommunityPack(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["community-packs"] });
    },
  });
}
