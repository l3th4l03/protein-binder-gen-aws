# AWS Permissions Setup for Protein Binder Pipeline

## Problem
Your AWS user `protein-binder-generator` lacks the necessary IAM permissions to deploy the protein binder pipeline. This guide provides multiple solutions to fix the permissions.

## Current Error Analysis
```
User: arn:aws:iam::343075903480:user/protein-binder-generator is not authorized to perform:
- ec2:DescribeAvailabilityZones
- cloudformation:CreateStack
```

## Solution Options

### Option 1: AWS Console (Recommended for Beginners)

#### Step 1: Login as Administrator
1. Go to [AWS Console](https://console.aws.amazon.com/)
2. Sign in with an account that has administrative privileges
3. Navigate to **IAM** service

#### Step 2: Find Your User
1. Click **Users** in the left sidebar
2. Search for and click on **protein-binder-generator**

#### Step 3A: Quick Fix - Attach AdministratorAccess (Broad Permissions)
1. Click the **Permissions** tab
2. Click **Add permissions** → **Attach existing policies directly**
3. Search for `AdministratorAccess`
4. Check the box next to **AdministratorAccess**
5. Click **Next: Review** → **Add permissions**

#### Step 3B: Secure Fix - Create Custom Policy (Recommended)
1. First, create the custom policy:
   - Go to **IAM** → **Policies** → **Create policy**
   - Click **JSON** tab
   - Copy and paste the contents from `iam-policy.json` file in this repository
   - Click **Next: Tags** → **Next: Review**
   - Name: `ProteinBinderPipelinePolicy`
   - Description: `Permissions for deploying protein binder generation pipeline`
   - Click **Create policy**

2. Then attach it to your user:
   - Go back to **Users** → **protein-binder-generator**
   - Click **Permissions** tab → **Add permissions**
   - Select **Attach existing policies directly**
   - Search for `ProteinBinderPipelinePolicy`
   - Check the box and click **Add permissions**

---

### Option 2: AWS CLI Commands (For Advanced Users)

#### Step 1: Create the Custom Policy
```bash
# Create the IAM policy
aws iam create-policy \
    --policy-name ProteinBinderPipelinePolicy \
    --policy-document file://iam-policy.json \
    --description "Permissions for protein binder generation pipeline"
```

#### Step 2: Attach Policy to User
```bash
# Get your account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Attach the policy to your user
aws iam attach-user-policy \
    --user-name protein-binder-generator \
    --policy-arn arn:aws:iam::${ACCOUNT_ID}:policy/ProteinBinderPipelinePolicy
```

#### Alternative: Attach AdministratorAccess (Quick but broad)
```bash
aws iam attach-user-policy \
    --user-name protein-binder-generator \
    --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
```

---

### Option 3: Use Different AWS Credentials

If you have access to another AWS user/role with administrative privileges:

1. **Create new AWS credentials:**
   ```bash
   aws configure --profile admin
   # Enter credentials for admin user
   ```

2. **Use admin profile for deployment:**
   ```bash
   export AWS_PROFILE=admin
   ./deploy.sh
   ```

3. **Or modify deploy.sh temporarily:**
   ```bash
   # Add this line at the top of deploy.sh
   export AWS_PROFILE=admin
   ```

---

## Verification Steps

After applying permissions, verify they work:

```bash
# Test basic permissions
aws ec2 describe-availability-zones
aws sts get-caller-identity

# Test CloudFormation permissions
aws cloudformation describe-stacks --region us-east-2

# If these work without errors, you can proceed with deployment
./deploy.sh
```

## Security Best Practices

### For Production Environments:
1. **Use the custom policy** instead of AdministratorAccess
2. **Remove permissions after deployment** if this is a one-time setup
3. **Use IAM roles** instead of user credentials when possible
4. **Enable MFA** on accounts with administrative privileges

### For Development/Testing:
- AdministratorAccess is acceptable for quick setup
- Consider using temporary credentials via AWS SSO or assume role

## Troubleshooting

### Common Issues:

1. **"Access Denied" for specific resources:**
   - The custom policy may be missing some permissions
   - Add the specific permission to the policy JSON
   - Re-apply the policy

2. **Policy already exists error:**
   ```bash
   # Delete existing policy first
   aws iam delete-policy --policy-arn arn:aws:iam::ACCOUNT_ID:policy/ProteinBinderPipelinePolicy
   # Then recreate it
   ```

3. **Still getting permission errors after applying:**
   - Wait 1-2 minutes for permissions to propagate
   - Check if you're using the correct AWS profile/credentials
   - Verify the policy was attached: `aws iam list-attached-user-policies --user-name protein-binder-generator`

4. **Cannot modify IAM permissions (chicken-and-egg problem):**
   - You need to use an AWS account with existing administrative privileges
   - Contact your AWS account owner/administrator
   - Use AWS root account credentials (not recommended for regular use)

## Next Steps

After fixing permissions, you can proceed with deployment:

```bash
# Deploy the protein binder pipeline
./deploy.sh

# Monitor deployment progress
aws cloudformation describe-stacks --stack-name protein-binder-pipeline --query 'Stacks[0].StackStatus'
```

The deployment will create all necessary AWS resources in your account: S3 bucket, DynamoDB tables, AWS Batch compute environment, Lambda function, and more.