"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Loader2,
  AlertCircle,
  Plus,
  Trash2,
  Edit2,
  KeyRound,
  CheckCircle2,
  XCircle,
  Clock,
  Layout,
  Eye,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/toast";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuth, getAuthHeaders } from "@/hooks/use-auth";
import { useRouter } from "next/navigation";

// Animated icons
import { UsersIcon } from "@/components/ui/users";
import { ChartBarIncreasingIcon } from "@/components/ui/chart-bar-increasing";
import { FileCheckIcon } from "@/components/ui/file-check";
import { ClockIcon } from "@/components/ui/clock";
import { ShieldCheckIcon } from "@/components/ui/shield-check";
import { LayersIcon } from "@/components/ui/layers";

import { api, type Schema, type Workflow } from "@/lib/api";
import { formatApiErrorDetail } from "@/lib/format-api-error";
import { Zap } from "lucide-react";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

function buildCreateUserPayload(data: {
  username: string;
  password: string;
  email: string;
  display_name: string;
  role: string;
}) {
  const email = data.email?.trim();
  return {
    username: data.username.trim(),
    password: data.password,
    role: data.role,
    ...(data.display_name?.trim() ? { display_name: data.display_name.trim() } : {}),
    ...(email ? { email } : {}),
  };
}

function buildUpdateUserPayload(data: {
  email: string;
  display_name: string;
  role: string;
  is_active: boolean;
}) {
  const displayName = data.display_name?.trim();
  const email = data.email?.trim();
  return {
    display_name: displayName || null,
    role: data.role,
    is_active: data.is_active,
    email: email || null,
  };
}

interface User {
  id: string;
  username: string;
  email?: string;
  display_name?: string;
  role: string;
  is_active: boolean;
  created_at?: string;
  last_login_at?: string;
}

interface DashboardStats {
  total_users: number;
  active_users: number;
  total_jobs: number;
  completed_jobs: number;
  failed_jobs: number;
  jobs_today: number;
  jobs_this_week: number;
  jobs_this_month: number;
  top_users: Array<{ user_id: string; username: string; display_name?: string; job_count: number }>;
  recent_activity: Array<{
    job_id: string;
    document_name: string;
    doc_type: string;
    status: string;
    username: string;
    created_at: string;
  }>;
}

interface Role {
  value: string;
  label: string;
  description: string;
}

export default function AdminPage() {
  const { isAdmin, isLoading: authLoading } = useAuth();
  const router = useRouter();
  const queryClient = useQueryClient();

  // Dialog states
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [resetPasswordDialogOpen, setResetPasswordDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);

  // Form states
  const [newUser, setNewUser] = useState({
    username: "",
    password: "",
    email: "",
    display_name: "",
    role: "viewer",
  });
  const [editUser, setEditUser] = useState({
    email: "",
    display_name: "",
    role: "",
    is_active: true,
  });
  const [newPassword, setNewPassword] = useState("");

  // Schema review states
  const [reviewDialogOpen, setReviewDialogOpen] = useState(false);
  const [selectedSchema, setSelectedSchema] = useState<Schema | null>(null);
  const [reviewNotes, setReviewNotes] = useState("");
  const [activeTab, setActiveTab] = useState("users");

  // Workflow review states
  const [workflowReviewDialogOpen, setWorkflowReviewDialogOpen] = useState(false);
  const [selectedWorkflow, setSelectedWorkflow] = useState<Workflow | null>(null);
  const [workflowReviewNotes, setWorkflowReviewNotes] = useState("");

  // Fetch dashboard stats
  const { data: stats, isLoading: statsLoading } = useQuery<DashboardStats>({
    queryKey: ["admin", "stats"],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/api/admin/dashboard/stats`, {
        headers: getAuthHeaders(),
      });
      if (!response.ok) throw new Error("Failed to fetch stats");
      return response.json();
    },
  });

  // Fetch users
  const { data: usersData, isLoading: usersLoading } = useQuery<{ users: User[]; total: number }>({
    queryKey: ["admin", "users"],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/api/admin/users`, {
        headers: getAuthHeaders(),
      });
      if (!response.ok) throw new Error("Failed to fetch users");
      return response.json();
    },
  });

  // Fetch available roles
  const { data: rolesData } = useQuery<{ roles: Role[] }>({
    queryKey: ["admin", "roles"],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/api/admin/roles`, {
        headers: getAuthHeaders(),
      });
      if (!response.ok) throw new Error("Failed to fetch roles");
      return response.json();
    },
  });

  // Fetch pending schemas for review
  const { data: pendingSchemas, isLoading: schemasLoading } = useQuery<Schema[]>({
    queryKey: ["admin", "pendingSchemas"],
    queryFn: () => api.getPendingSchemas(),
  });

  // Fetch pending workflows for review
  const { data: pendingWorkflows, isLoading: workflowsLoading } = useQuery<Workflow[]>({
    queryKey: ["admin", "pendingWorkflows"],
    queryFn: () => api.getPendingWorkflows(),
  });

  // Create user mutation
  const createUserMutation = useMutation({
    mutationFn: async (data: typeof newUser) => {
      const response = await fetch(`${API_BASE_URL}/api/admin/users`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeaders(),
        },
        body: JSON.stringify(buildCreateUserPayload(data)),
      });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(formatApiErrorDetail(body.detail, "Failed to create user"));
      }
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "stats"] });
      setCreateDialogOpen(false);
      setNewUser({ username: "", password: "", email: "", display_name: "", role: "viewer" });
      toast({ title: "User created", description: "New user has been created successfully." });
    },
    onError: (error: Error) => {
      toast({ title: "Failed to create user", description: error.message, variant: "destructive" });
    },
  });

  // Update user mutation
  const updateUserMutation = useMutation({
    mutationFn: async ({ userId, data }: { userId: string; data: typeof editUser }) => {
      const response = await fetch(`${API_BASE_URL}/api/admin/users/${userId}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeaders(),
        },
        body: JSON.stringify(buildUpdateUserPayload(data)),
      });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(formatApiErrorDetail(body.detail, "Failed to update user"));
      }
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      setEditDialogOpen(false);
      setSelectedUser(null);
      toast({ title: "User updated", description: "User has been updated successfully." });
    },
    onError: (error: Error) => {
      toast({ title: "Failed to update user", description: error.message, variant: "destructive" });
    },
  });

  // Reset password mutation
  const resetPasswordMutation = useMutation({
    mutationFn: async ({ userId, newPassword }: { userId: string; newPassword: string }) => {
      const response = await fetch(`${API_BASE_URL}/api/admin/users/${userId}/reset-password`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeaders(),
        },
        body: JSON.stringify({ new_password: newPassword }),
      });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(formatApiErrorDetail(body.detail, "Failed to reset password"));
      }
      return response.json();
    },
    onSuccess: () => {
      setResetPasswordDialogOpen(false);
      setNewPassword("");
      setSelectedUser(null);
      toast({ title: "Password reset", description: "User password has been reset." });
    },
    onError: (error: Error) => {
      toast({ title: "Failed to reset password", description: error.message, variant: "destructive" });
    },
  });

  // Delete user mutation
  const deleteUserMutation = useMutation({
    mutationFn: async (userId: string) => {
      const response = await fetch(`${API_BASE_URL}/api/admin/users/${userId}`, {
        method: "DELETE",
        headers: getAuthHeaders(),
      });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(formatApiErrorDetail(body.detail, "Failed to delete user"));
      }
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "stats"] });
      setDeleteDialogOpen(false);
      setSelectedUser(null);
      toast({ title: "User deleted", description: "User has been deleted successfully." });
    },
    onError: (error: Error) => {
      toast({ title: "Failed to delete user", description: error.message, variant: "destructive" });
    },
  });

  // Review schema mutation
  const reviewSchemaMutation = useMutation({
    mutationFn: async ({ schemaId, approved, notes }: { schemaId: string; approved: boolean; notes?: string }) => {
      return api.reviewSchema(schemaId, approved, notes);
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["admin", "pendingSchemas"] });
      queryClient.invalidateQueries({ queryKey: ["pendingSchemaCount"] });
      queryClient.invalidateQueries({ queryKey: ["schemas"] });
      setReviewDialogOpen(false);
      setSelectedSchema(null);
      setReviewNotes("");
      toast({
        title: variables.approved ? "Schema approved" : "Schema rejected",
        description: variables.approved
          ? "The schema has been published and is now visible to all users."
          : "The schema has been rejected. The owner will be notified.",
      });
    },
    onError: (error: Error) => {
      toast({ title: "Failed to review schema", description: error.message, variant: "destructive" });
    },
  });

  // Review workflow mutation
  const reviewWorkflowMutation = useMutation({
    mutationFn: async ({ workflowId, approved, notes }: { workflowId: string; approved: boolean; notes?: string }) => {
      return api.reviewWorkflow(workflowId, approved, notes);
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["admin", "pendingWorkflows"] });
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      setWorkflowReviewDialogOpen(false);
      setSelectedWorkflow(null);
      setWorkflowReviewNotes("");
      toast({
        title: variables.approved ? "Workflow approved" : "Workflow rejected",
        description: variables.approved
          ? "The workflow has been published and is now accessible via external API."
          : "The workflow has been rejected. The owner will be notified.",
      });
    },
    onError: (error: Error) => {
      toast({ title: "Failed to review workflow", description: error.message, variant: "destructive" });
    },
  });

  // Redirect non-admins
  if (!authLoading && !isAdmin) {
    router.push("/");
    return null;
  }

  if (authLoading || statsLoading) {
    return (
      <div className="container mx-auto py-6 px-4 max-w-6xl">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  const roles = rolesData?.roles || [];

  const handleEditUser = (user: User) => {
    setSelectedUser(user);
    setEditUser({
      email: user.email || "",
      display_name: user.display_name || "",
      role: user.role,
      is_active: user.is_active,
    });
    setEditDialogOpen(true);
  };

  const handleResetPassword = (user: User) => {
    setSelectedUser(user);
    setNewPassword("");
    setResetPasswordDialogOpen(true);
  };

  const handleDeleteUser = (user: User) => {
    setSelectedUser(user);
    setDeleteDialogOpen(true);
  };

  const handleReviewSchema = (schema: Schema) => {
    setSelectedSchema(schema);
    setReviewNotes("");
    setReviewDialogOpen(true);
  };

  const handleApproveSchema = () => {
    if (selectedSchema) {
      reviewSchemaMutation.mutate({
        schemaId: selectedSchema.id,
        approved: true,
        notes: reviewNotes || undefined,
      });
    }
  };

  const handleRejectSchema = () => {
    if (selectedSchema) {
      reviewSchemaMutation.mutate({
        schemaId: selectedSchema.id,
        approved: false,
        notes: reviewNotes || undefined,
      });
    }
  };

  const handleReviewWorkflow = (workflow: Workflow) => {
    setSelectedWorkflow(workflow);
    setWorkflowReviewNotes("");
    setWorkflowReviewDialogOpen(true);
  };

  const handleApproveWorkflow = () => {
    if (selectedWorkflow) {
      reviewWorkflowMutation.mutate({
        workflowId: selectedWorkflow.id,
        approved: true,
        notes: workflowReviewNotes || undefined,
      });
    }
  };

  const handleRejectWorkflow = () => {
    if (selectedWorkflow) {
      reviewWorkflowMutation.mutate({
        workflowId: selectedWorkflow.id,
        approved: false,
        notes: workflowReviewNotes || undefined,
      });
    }
  };

  // Format doc_type for display
  const formatDocType = (docType: string) => {
    return docType
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
  };

  const getRoleBadgeVariant = (role: string) => {
    switch (role) {
      case "admin":
        return "default";
      case "contributor":
        return "secondary";
      default:
        return "outline";
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "completed":
        return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
      case "failed":
        return <XCircle className="h-4 w-4 text-destructive" />;
      default:
        return <Clock className="h-4 w-4 text-amber-500" />;
    }
  };

  return (
    <div className="container mx-auto py-6 px-4 max-w-6xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <ShieldCheckIcon size={24} />
            Admin Dashboard
          </h1>
          <p className="text-muted-foreground">Manage users and view platform statistics</p>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <UsersIcon size={16} />
              Total Users
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.total_users || 0}</div>
            <p className="text-xs text-muted-foreground">{stats?.active_users || 0} active</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <FileCheckIcon size={16} />
              Total Jobs
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.total_jobs || 0}</div>
            <p className="text-xs text-muted-foreground">{stats?.completed_jobs || 0} completed</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <ChartBarIncreasingIcon size={16} />
              This Week
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.jobs_this_week || 0}</div>
            <p className="text-xs text-muted-foreground">{stats?.jobs_today || 0} today</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <ClockIcon size={16} />
              This Month
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.jobs_this_month || 0}</div>
            <p className="text-xs text-muted-foreground">{stats?.failed_jobs || 0} failed</p>
          </CardContent>
        </Card>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
        <TabsList>
          <TabsTrigger value="users" className="flex items-center gap-2">
            <UsersIcon size={16} />
            Users
          </TabsTrigger>
          <TabsTrigger value="schemas" className="flex items-center gap-2">
            <LayersIcon size={16} />
            Schema Reviews
            {pendingSchemas && pendingSchemas.length > 0 && (
              <Badge variant="destructive" className="h-5 min-w-[20px] px-1.5 text-xs">
                {pendingSchemas.length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="workflows" className="flex items-center gap-2">
            <Zap size={16} />
            Workflow Reviews
            {pendingWorkflows && pendingWorkflows.length > 0 && (
              <Badge variant="destructive" className="h-5 min-w-[20px] px-1.5 text-xs">
                {pendingWorkflows.length}
              </Badge>
            )}
          </TabsTrigger>
        </TabsList>

        {/* Users Tab */}
        <TabsContent value="users">
          <div className="grid md:grid-cols-3 gap-6">
            {/* Users Table */}
            <Card className="md:col-span-2">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-lg flex items-center gap-2">
                      <UsersIcon size={20} />
                      User Management
                    </CardTitle>
                    <CardDescription>Add, edit, and manage user accounts</CardDescription>
                  </div>
                  <Button onClick={() => setCreateDialogOpen(true)} size="sm">
                    <Plus className="h-4 w-4 mr-1" />
                    Add User
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                {usersLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  </div>
                ) : (
                  <div className="border rounded-lg">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>User</TableHead>
                          <TableHead>Role</TableHead>
                          <TableHead>Status</TableHead>
                          <TableHead className="text-right">Actions</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {usersData?.users.map((user) => (
                          <TableRow key={user.id}>
                            <TableCell>
                              <div>
                                <div className="font-medium">
                                  {user.display_name && user.display_name.trim() ? user.display_name : "—"}
                                </div>
                                <div className="text-xs text-muted-foreground">
                                  {user.email && user.email.trim() ? user.email : "—"} · {user.username}
                                </div>
                              </div>
                            </TableCell>
                            <TableCell>
                              <Badge variant={getRoleBadgeVariant(user.role)} className="capitalize">
                                {user.role}
                              </Badge>
                            </TableCell>
                            <TableCell>
                              <Badge variant={user.is_active ? "outline" : "secondary"}>
                                {user.is_active ? "Active" : "Inactive"}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-right">
                              <div className="flex items-center justify-end gap-1">
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-8 w-8"
                                  title="Edit user"
                                  onClick={() => handleEditUser(user)}
                                >
                                  <Edit2 className="h-4 w-4" />
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-8 w-8"
                                  title="Reset password"
                                  onClick={() => handleResetPassword(user)}
                                >
                                  <KeyRound className="h-4 w-4" />
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-8 w-8 text-destructive hover:text-destructive"
                                  title="Delete user"
                                  onClick={() => handleDeleteUser(user)}
                                  disabled={user.username === "default"}
                                >
                                  <Trash2 className="h-4 w-4" />
                                </Button>
                              </div>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Recent Activity & Top Users */}
            <div className="space-y-6">
              {/* Top Users */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg">Top Contributors</CardTitle>
                  <CardDescription>Users with most processed documents</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="space-y-3">
                    {stats?.top_users.slice(0, 5).map((u, i) => (
                      <div key={u.user_id} className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-muted-foreground w-4">{i + 1}.</span>
                          <span className="text-sm">{u.display_name || u.username}</span>
                        </div>
                        <Badge variant="secondary">{u.job_count} jobs</Badge>
                      </div>
                    ))}
                    {(!stats?.top_users || stats.top_users.length === 0) && (
                      <p className="text-sm text-muted-foreground text-center py-4">No activity yet</p>
                    )}
                  </div>
                </CardContent>
              </Card>

              {/* Recent Activity */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg">Recent Activity</CardTitle>
                  <CardDescription>Latest document processing jobs</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="space-y-3">
                    {stats?.recent_activity.slice(0, 5).map((activity) => (
                      <div key={activity.job_id} className="flex items-start gap-2">
                        {getStatusIcon(activity.status)}
                        <div className="flex-1 min-w-0">
                          <p className="text-sm truncate">{activity.document_name}</p>
                          <p className="text-xs text-muted-foreground">
                            {activity.username} - {activity.doc_type}
                          </p>
                        </div>
                      </div>
                    ))}
                    {(!stats?.recent_activity || stats.recent_activity.length === 0) && (
                      <p className="text-sm text-muted-foreground text-center py-4">No recent activity</p>
                    )}
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>

        {/* Schema Reviews Tab */}
        <TabsContent value="schemas">
          <Card>
            <CardContent className="pt-6">
              {schemasLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : !pendingSchemas || pendingSchemas.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12">
                  <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-4">
                    <CheckCircle2 className="h-8 w-8 text-muted-foreground" />
                  </div>
                  <h3 className="text-lg font-semibold mb-1">All caught up!</h3>
                  <p className="text-sm text-muted-foreground text-center max-w-sm">
                    No schemas pending review. Check back later when users submit new schemas for approval.
                  </p>
                </div>
              ) : (
                <div className="space-y-4">
                  {pendingSchemas.map((schema) => (
                    <Card key={schema.id} className="border">
                      <CardContent className="p-4">
                        <div className="flex items-start justify-between">
                          <div className="space-y-2 flex-1">
                            <div className="flex items-center gap-2">
                              <Layout className="h-4 w-4 text-muted-foreground" />
                              <h4 className="font-medium">{schema.name}</h4>
                              <Badge variant="outline">{formatDocType(schema.doc_type)}</Badge>
                              <Badge variant="secondary" className="flex items-center gap-1">
                                <Clock className="h-3 w-3" />
                                Pending
                              </Badge>
                            </div>
                            <p className="text-sm text-muted-foreground line-clamp-2">
                              {schema.description || "No description provided"}
                            </p>
                            <div className="flex items-center gap-4 text-xs text-muted-foreground">
                              {schema.owner && (
                                <span>
                                  Submitted by: <span className="font-medium">{schema.owner.display_name || schema.owner.username}</span>
                                </span>
                              )}
                              {schema.created_at && (
                                <span>
                                  Created: {new Date(schema.created_at).toLocaleDateString()}
                                </span>
                              )}
                              <span>
                                Parts: {schema.parts_config?.length || 0}
                              </span>
                            </div>
                          </div>
                          <div className="flex items-center gap-2 ml-4">
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => window.open(`/schemas/${schema.id}`, '_blank')}
                            >
                              <Eye className="h-4 w-4 mr-1" />
                              Preview
                            </Button>
                            <Button
                              size="sm"
                              onClick={() => handleReviewSchema(schema)}
                            >
                              Review
                            </Button>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Workflow Reviews Tab */}
        <TabsContent value="workflows">
          <Card>
            <CardContent className="pt-6">
              {workflowsLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : !pendingWorkflows || pendingWorkflows.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12">
                  <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-4">
                    <CheckCircle2 className="h-8 w-8 text-muted-foreground" />
                  </div>
                  <h3 className="text-lg font-semibold mb-1">All caught up!</h3>
                  <p className="text-sm text-muted-foreground text-center max-w-sm">
                    No workflows pending review. Check back later when users submit workflows for publishing.
                  </p>
                </div>
              ) : (
                <div className="space-y-4">
                  {pendingWorkflows.map((workflow) => (
                    <Card key={workflow.id} className="border">
                      <CardContent className="p-4">
                        <div className="flex items-start justify-between">
                          <div className="space-y-2 flex-1">
                            <div className="flex items-center gap-2">
                              <Zap className="h-4 w-4 text-muted-foreground" />
                              <h4 className="font-medium">{workflow.name}</h4>
                              <code className="text-xs bg-muted px-1.5 py-0.5 rounded">
                                /{workflow.slug}
                              </code>
                              <Badge variant="secondary" className="flex items-center gap-1">
                                <Clock className="h-3 w-3" />
                                Pending
                              </Badge>
                            </div>
                            <p className="text-sm text-muted-foreground line-clamp-2">
                              {workflow.description || "No description provided"}
                            </p>
                            <div className="flex items-center gap-4 text-xs text-muted-foreground">
                              {workflow.owner && (
                                <span>
                                  Submitted by: <span className="font-medium">{workflow.owner.display_name || workflow.owner.username}</span>
                                </span>
                              )}
                              {workflow.schema_info && (
                                <span>
                                  Schema: <span className="font-medium">{workflow.schema_info.name}</span>
                                </span>
                              )}
                              <span>
                                Mode: {workflow.response_mode === "sync" ? "Synchronous" : "Asynchronous"}
                              </span>
                              <span>
                                Rate: {workflow.rate_limit_per_minute}/min
                              </span>
                            </div>
                          </div>
                          <div className="flex items-center gap-2 ml-4">
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => window.open(`/workflows/${workflow.id}`, '_blank')}
                            >
                              <Eye className="h-4 w-4 mr-1" />
                              Preview
                            </Button>
                            <Button
                              size="sm"
                              onClick={() => handleReviewWorkflow(workflow)}
                            >
                              Review
                            </Button>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Create User Dialog */}
      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create New User</DialogTitle>
            <DialogDescription>Add a new user to the platform</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="new-username">
                Username <span className="text-destructive">*</span>
              </Label>
              <Input
                id="new-username"
                value={newUser.username}
                onChange={(e) => setNewUser({ ...newUser, username: e.target.value })}
                placeholder="johndoe"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-password">
                Password <span className="text-destructive">*</span>
              </Label>
              <Input
                id="new-password"
                type="password"
                value={newUser.password}
                onChange={(e) => setNewUser({ ...newUser, password: e.target.value })}
                placeholder="Minimum 8 characters"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-display-name">Display Name (optional)</Label>
              <Input
                id="new-display-name"
                value={newUser.display_name}
                onChange={(e) => setNewUser({ ...newUser, display_name: e.target.value })}
                placeholder="John Doe"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-email">Email (optional)</Label>
              <Input
                id="new-email"
                type="email"
                value={newUser.email}
                onChange={(e) => setNewUser({ ...newUser, email: e.target.value })}
                placeholder="john@example.com"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-role">Role</Label>
              <Select
                value={newUser.role}
                onValueChange={(value) => setNewUser({ ...newUser, role: value })}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select role" />
                </SelectTrigger>
                <SelectContent>
                  {roles.map((role) => (
                    <SelectItem key={role.value} value={role.value}>
                      <div>
                        <span className="font-medium">{role.label}</span>
                        <span className="text-xs text-muted-foreground ml-2">{role.description}</span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => createUserMutation.mutate(newUser)}
              disabled={createUserMutation.isPending || !newUser.username || !newUser.password}
            >
              {createUserMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Create User
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit User Dialog */}
      <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit User</DialogTitle>
            <DialogDescription>
              Update user information for {selectedUser?.display_name || selectedUser?.username}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="edit-display-name">Display Name</Label>
              <Input
                id="edit-display-name"
                value={editUser.display_name}
                onChange={(e) => setEditUser({ ...editUser, display_name: e.target.value })}
                placeholder="John Doe"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-email">Email</Label>
              <Input
                id="edit-email"
                type="email"
                value={editUser.email}
                onChange={(e) => setEditUser({ ...editUser, email: e.target.value })}
                placeholder="john@example.com"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-role">Role</Label>
              <Select
                value={editUser.role}
                onValueChange={(value) => setEditUser({ ...editUser, role: value })}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select role" />
                </SelectTrigger>
                <SelectContent>
                  {roles.map((role) => (
                    <SelectItem key={role.value} value={role.value}>
                      {role.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Active Status</Label>
                <p className="text-xs text-muted-foreground">Inactive users cannot log in</p>
              </div>
              <Switch
                checked={editUser.is_active}
                onCheckedChange={(checked) => setEditUser({ ...editUser, is_active: checked })}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() =>
                selectedUser && updateUserMutation.mutate({ userId: selectedUser.id, data: editUser })
              }
              disabled={updateUserMutation.isPending}
            >
              {updateUserMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Save Changes
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Reset Password Dialog */}
      <Dialog open={resetPasswordDialogOpen} onOpenChange={setResetPasswordDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reset Password</DialogTitle>
            <DialogDescription>
              Set a new password for {selectedUser?.display_name || selectedUser?.username}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="reset-password">New Password</Label>
              <Input
                id="reset-password"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="Minimum 8 characters"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setResetPasswordDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() =>
                selectedUser && resetPasswordMutation.mutate({ userId: selectedUser.id, newPassword })
              }
              disabled={resetPasswordMutation.isPending || newPassword.length < 8}
            >
              {resetPasswordMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Reset Password
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete User Dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete User</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete {selectedUser?.display_name || selectedUser?.username}? This
              action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => selectedUser && deleteUserMutation.mutate(selectedUser.id)}
              disabled={deleteUserMutation.isPending}
            >
              {deleteUserMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Delete User
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Schema Review Dialog */}
      <Dialog open={reviewDialogOpen} onOpenChange={setReviewDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Review Schema</DialogTitle>
            <DialogDescription>
              Review and approve or reject "{selectedSchema?.name}"
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            {selectedSchema && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Layout className="h-4 w-4 text-muted-foreground" />
                  <span className="font-medium">{selectedSchema.name}</span>
                  <Badge variant="outline">{formatDocType(selectedSchema.doc_type)}</Badge>
                </div>
                <p className="text-sm text-muted-foreground">
                  {selectedSchema.description || "No description provided"}
                </p>
                {selectedSchema.owner && (
                  <p className="text-xs text-muted-foreground">
                    Submitted by: <span className="font-medium">{selectedSchema.owner.display_name || selectedSchema.owner.username}</span>
                  </p>
                )}
                {selectedSchema.submit_notes && (
                  <div className="rounded-md border bg-muted/40 p-3 text-sm text-foreground">
                    <p className="text-xs font-medium text-muted-foreground mb-1">Publisher Comment</p>
                    <p>{selectedSchema.submit_notes}</p>
                  </div>
                )}
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="review-notes">
                Review Notes <span className="text-red-500">*</span>
              </Label>
              <Textarea
                id="review-notes"
                value={reviewNotes}
                onChange={(e) => setReviewNotes(e.target.value)}
                placeholder="Add feedback or notes for the schema owner (required)..."
                rows={3}
              />
              <p className="text-xs text-muted-foreground">
                Review notes are required to approve or reject a schema.
              </p>
            </div>
          </div>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setReviewDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleRejectSchema}
              disabled={reviewSchemaMutation.isPending || !reviewNotes.trim()}
            >
              {reviewSchemaMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              <XCircle className="h-4 w-4 mr-1" />
              Reject
            </Button>
            <Button
              onClick={handleApproveSchema}
              disabled={reviewSchemaMutation.isPending || !reviewNotes.trim()}
            >
              {reviewSchemaMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              <CheckCircle2 className="h-4 w-4 mr-1" />
              Approve & Publish
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Workflow Review Dialog */}
      <Dialog open={workflowReviewDialogOpen} onOpenChange={setWorkflowReviewDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Review Workflow</DialogTitle>
            <DialogDescription>
              Review and approve or reject "{selectedWorkflow?.name}"
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            {selectedWorkflow && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Zap className="h-4 w-4 text-muted-foreground" />
                  <span className="font-medium">{selectedWorkflow.name}</span>
                  <code className="text-xs bg-muted px-1.5 py-0.5 rounded">
                    /{selectedWorkflow.slug}
                  </code>
                </div>
                <p className="text-sm text-muted-foreground">
                  {selectedWorkflow.description || "No description provided"}
                </p>
                <div className="text-xs text-muted-foreground space-y-1">
                  {selectedWorkflow.owner && (
                    <p>
                      Submitted by: <span className="font-medium">{selectedWorkflow.owner.display_name || selectedWorkflow.owner.username}</span>
                    </p>
                  )}
                  {selectedWorkflow.submit_notes && (
                    <div className="rounded-md border bg-muted/40 p-3 text-sm text-foreground mt-2">
                      <p className="text-xs font-medium text-muted-foreground mb-1">Publisher Comment</p>
                      <p>{selectedWorkflow.submit_notes}</p>
                    </div>
                  )}
                  {selectedWorkflow.schema_info && (
                    <p>
                      Schema: <span className="font-medium">{selectedWorkflow.schema_info.name}</span>
                    </p>
                  )}
                  <p>
                    Response Mode: <span className="font-medium">{selectedWorkflow.response_mode === "sync" ? "Synchronous" : "Asynchronous"}</span>
                  </p>
                  <p>
                    Rate Limits: <span className="font-medium">{selectedWorkflow.rate_limit_per_minute}/min, {selectedWorkflow.rate_limit_per_day}/day</span>
                  </p>
                </div>
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="workflow-review-notes">
                Review Notes <span className="text-red-500">*</span>
              </Label>
              <Textarea
                id="workflow-review-notes"
                value={workflowReviewNotes}
                onChange={(e) => setWorkflowReviewNotes(e.target.value)}
                placeholder="Add feedback or notes for the workflow owner (required)..."
                rows={3}
              />
              <p className="text-xs text-muted-foreground">
                Review notes are required to approve or reject a workflow.
              </p>
            </div>
          </div>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setWorkflowReviewDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleRejectWorkflow}
              disabled={reviewWorkflowMutation.isPending || !workflowReviewNotes.trim()}
            >
              {reviewWorkflowMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              <XCircle className="h-4 w-4 mr-1" />
              Reject
            </Button>
            <Button
              onClick={handleApproveWorkflow}
              disabled={reviewWorkflowMutation.isPending || !workflowReviewNotes.trim()}
            >
              {reviewWorkflowMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              <CheckCircle2 className="h-4 w-4 mr-1" />
              Approve & Publish
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
