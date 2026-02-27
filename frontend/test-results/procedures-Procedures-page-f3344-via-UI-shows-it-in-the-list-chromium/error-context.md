# Page snapshot

```yaml
- generic [ref=e1]:
  - generic [ref=e3]:
    - generic [ref=e4]:
      - img [ref=e6]
      - heading "LangOrch" [level=1] [ref=e8]
      - paragraph [ref=e9]: Agentic Automation Platform
    - generic [ref=e10]:
      - heading "Sign in to your account" [level=2] [ref=e11]
      - generic [ref=e12]:
        - generic [ref=e13]:
          - generic [ref=e14]: Username
          - textbox "admin" [active] [ref=e15]
        - generic [ref=e16]:
          - generic [ref=e17]: Password
          - generic [ref=e18]:
            - textbox "••••••••" [ref=e19]
            - button [ref=e20] [cursor=pointer]:
              - img [ref=e21]
        - button "Sign in" [disabled] [ref=e24]
      - generic [ref=e25]:
        - paragraph [ref=e26]: Default credentials
        - paragraph [ref=e27]: "Username: admin / Password: admin123"
    - paragraph [ref=e28]: Enterprise SSO (Azure AD / LDAP) can be configured via the platform settings.
  - alert [ref=e29]
```