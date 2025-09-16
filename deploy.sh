#!/bin/bash

# RECOMMENDED DEPLOYMENT SCRIPT for Protein Binder Pipeline
# This script includes comprehensive error handling, status checks, and user feedback.
# For a simpler version without error handling, see deploy-simple.sh

set -e  # Exit on any error

echo "Protein Binder Pipeline - Deploy"
echo "========================================"

STACK_NAME=protein-binder-pipeline
REGION=$(aws ec2 describe-availability-zones --output text --query 'AvailabilityZones[0].[RegionName]')
ACCOUNT_NUMBER=$(aws sts get-caller-identity --query 'Account' --output text)

echo "Account: $ACCOUNT_NUMBER"
echo "Region: $REGION"
echo ""

# Step 1: Handle existing stack
echo "Checking for existing stack..."
if aws cloudformation describe-stacks --stack-name $STACK_NAME &>/dev/null; then
    STACK_STATUS=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].StackStatus' --output text)
    echo "   Found stack with status: $STACK_STATUS"

    if [ "$STACK_STATUS" = "ROLLBACK_COMPLETE" ] || [ "$STACK_STATUS" = "CREATE_FAILED" ]; then
        echo "Deleting failed stack..."
        aws cloudformation delete-stack --stack-name $STACK_NAME
        echo "Waiting for deletion..."
        aws cloudformation wait stack-delete-complete --stack-name $STACK_NAME
        echo "Deleted!"
    elif [ "$STACK_STATUS" = "CREATE_COMPLETE" ]; then
        echo "Stack already exists and is healthy"
    else
        echo "❌ Stack is in $STACK_STATUS state. Please check AWS console."
        exit 1
    fi
fi

# Step 2: Create CloudFormation stack
if ! aws cloudformation describe-stacks --stack-name $STACK_NAME &>/dev/null; then
    echo "Creating CloudFormation stack..."
    aws cloudformation create-stack \
        --stack-name $STACK_NAME \
        --parameters ParameterKey=StackName,ParameterValue=$STACK_NAME \
        --template-body file://template/template.yaml \
        --capabilities CAPABILITY_NAMED_IAM

    echo "⏳ Waiting for stack creation (5-10 minutes)..."
    aws cloudformation wait stack-create-complete --stack-name $STACK_NAME

    FINAL_STATUS=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].StackStatus' --output text)
    if [ "$FINAL_STATUS" != "CREATE_COMPLETE" ]; then
        echo "Stack creation failed: $FINAL_STATUS"
        echo "Check AWS Console for details"
        exit 1
    fi
    echo "✅ CloudFormation stack created successfully!"
fi

# Step 3: Build and push container
echo ""
echo "Building container..."
cd src/
docker build -t protein-binder-container . --quiet

echo "Tagging container..."
docker tag protein-binder-container $ACCOUNT_NUMBER.dkr.ecr.$REGION.amazonaws.com/$STACK_NAME-repository:latest

echo "Logging into ECR..."
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCOUNT_NUMBER.dkr.ecr.$REGION.amazonaws.com

echo "Pushing to ECR..."
docker push $ACCOUNT_NUMBER.dkr.ecr.$REGION.amazonaws.com/$STACK_NAME-repository:latest

# Step 4: Upload test file
cd ..
echo "Uploading test PDB file..."
aws s3 cp sample/il6r_target.pdb s3://$STACK_NAME-$ACCOUNT_NUMBER/targets/il6r_target.pdb

echo ""
echo "DEPLOYMENT COMPLETE!"
echo "======================"
echo ""
echo "Your pipeline is ready:"
echo "   • S3 Bucket: s3://$STACK_NAME-$ACCOUNT_NUMBER"
echo "   • Upload PDB files to: s3://$STACK_NAME-$ACCOUNT_NUMBER/targets/"
echo "   • Results appear in: s3://$STACK_NAME-$ACCOUNT_NUMBER/results/"
echo ""
echo "Monitor jobs with:"
echo "   aws dynamodb scan --table-name $STACK_NAME-jobs --query 'Items[].[job_id.S,status.S,pdb_name.S]' --output table"
echo ""
echo "AWS Console links:"
echo "   • DynamoDB: https://$REGION.console.aws.amazon.com/dynamodbv2/home?region=$REGION#item-explorer?table=$STACK_NAME-jobs"
echo "   • Batch Jobs: https://$REGION.console.aws.amazon.com/batch/home?region=$REGION#queues"
echo ""
echo "A test job should start automatically from the uploaded PDB file!"