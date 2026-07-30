-- CreateTable
CREATE TABLE "Content" (
    "contentId" TEXT NOT NULL PRIMARY KEY,
    "merchantId" TEXT NOT NULL,
    "merchantName" TEXT NOT NULL,
    "productId" TEXT NOT NULL,
    "productTitle" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "copy" TEXT NOT NULL,
    "videoUrl" TEXT NOT NULL,
    "sellingPointsJson" TEXT NOT NULL,
    "targetAudience" TEXT NOT NULL,
    "version" INTEGER NOT NULL,
    "status" TEXT NOT NULL,
    "submittedAt" DATETIME NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL
);

-- CreateTable
CREATE TABLE "Review" (
    "reviewId" TEXT NOT NULL PRIMARY KEY,
    "contentId" TEXT NOT NULL,
    "decision" TEXT NOT NULL,
    "reasonCode" TEXT,
    "comment" TEXT,
    "reviewerId" TEXT NOT NULL,
    "reviewerName" TEXT NOT NULL,
    "reviewedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "contentVersion" INTEGER NOT NULL,
    "previousStatus" TEXT NOT NULL,
    "nextStatus" TEXT NOT NULL,
    CONSTRAINT "Review_contentId_fkey" FOREIGN KEY ("contentId") REFERENCES "Content" ("contentId") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateIndex
CREATE INDEX "Content_status_submittedAt_idx" ON "Content"("status", "submittedAt");

-- CreateIndex
CREATE INDEX "Content_merchantId_idx" ON "Content"("merchantId");

-- CreateIndex
CREATE UNIQUE INDEX "Review_contentId_contentVersion_key" ON "Review"("contentId", "contentVersion");

-- CreateIndex
CREATE INDEX "Review_contentId_reviewedAt_idx" ON "Review"("contentId", "reviewedAt");

