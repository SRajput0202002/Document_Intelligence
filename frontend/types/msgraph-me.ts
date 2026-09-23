/** Subset of Microsoft Graph /me used by MSAL sign-in. */
export interface MSALGraphMeData {
  id?: string;
  displayName?: string;
  givenName?: string;
  surname?: string;
  mail?: string | null;
  userPrincipalName?: string;
  jobTitle?: string | null;
  officeLocation?: string | null;
}
