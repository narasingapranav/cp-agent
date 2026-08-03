class Solution:
    def maxProduct(self, n: int) -> int:
        l=[int(i) for i in str(n)]
        l.sort()
        return max(l[-1]*l[-2],l[0]*l[1])