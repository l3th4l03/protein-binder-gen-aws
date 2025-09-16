#!/bin/bash

# Cleanup script - removes all AWS resources created by the deployment scripts

SOURCE_REPOSITORY=$PWD

# Stack name should match the one used in deployment scripts
STACK_NAME=${1:-protein-binder-pipeline}

echo "Stack name: $STACK_NAME"
echo "======================================"

REGION=$(aws ec2 describe-availability-zones --output text --query 'AvailabilityZones[0].[RegionName]')
ACCOUNT_NUMBER=$(aws sts get-caller-identity --query 'Account' --output text)

echo 'Deleting Amazon ECR and S3 data'
# Delete all images from ECR repository (both tagged and untagged)
IMAGE_DIGESTS=$(aws ecr list-images --repository-name $STACK_NAME-repository --query 'imageIds[*]' --output json 2>/dev/null)
if [ "$IMAGE_DIGESTS" != "[]" ] && [ "$IMAGE_DIGESTS" != "" ]; then
    echo "Deleting ECR images..."
    aws ecr batch-delete-image --repository-name $STACK_NAME-repository --image-ids "$IMAGE_DIGESTS"
else
    echo "No ECR images to delete or repository doesn't exist"
fi

aws s3 --region $REGION rm s3://$STACK_NAME-$ACCOUNT_NUMBER --recursive

echo 'Cleaninup the CloudFormation Stack'
aws cloudformation delete-stack --stack-name $STACK_NAME

echo 'CloudFormation Stack - '$STACK_NAME ' Steps completed successfully!'